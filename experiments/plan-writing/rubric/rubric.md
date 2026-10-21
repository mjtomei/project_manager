# Technical document quality rubric

Rubric for [pm/plans/plan-doc-eval.md](../../../pm/plans/plan-doc-eval.md): the quality dimensions that judges score whole-document and continuation cases on, where each comes from, how to detect it, and which measures are ready for use. The machine-readable source is [dimensions.json](dimensions.json) with the bibliography in [references.json](references.json); the dimension reference below is generated from them. Judge prompts are rendered from [templates/](templates/) by [rubric.py](../rubric.py), and [fixtures/](fixtures/) holds a controlled pair for each dimension.

Status: no dimension or measure has calibration evidence yet. Every judge measure is `needs_calibration` until the runner and calibration PR reports consistency, agreement and bias sensitivity for it, per case type. Automatic candidates are diagnostics until they are shown to track calibrated judges.

## Survey

The survey covered the eight families of published guidance in the table below. Requirement standards define quality for individual statements and for sets of them. Plain-language standards and style guides define readability for a stated audience. The process templates of the communities in [sources.json](../sources.json) say what each genre owes its reviewers. Published analytic writing rubrics show how general writing quality is split into separately scored traits. The evaluation literature for generated text describes how fidelity and coherence have been measured and how LLM judges fail.

| Family | Sources | What they contribute |
|---|---|---|
| Requirement standards | ISO/IEC/IEEE 29148, INCOSE GtWR, NASA SE Handbook App. C, RFC 8174 | Statement and set characteristics: correct, unambiguous, complete, consistent, verifiable, traceable, appropriate in level, solution-free. |
| Architecture and design practice | ISO/IEC/IEEE 42010, Design Docs at Google, RFC 4101 | Rationale and alternatives as first-class content; design docs that are implementation manuals add little; overview models before implementor detail. |
| Plain language and style | ISO 24495-1, Federal Plain Language Guidelines, Google and Microsoft style guides, GOV.UK, Write the Docs, Diátaxis, Williams | Relevance to the reader, front-loading, omitting excess words, consistent terms; Write the Docs' ARID principle and Diátaxis' separation of purposes as counterweights that keep useful repetition and genre fit. |
| Process templates of the corpus | PEP 1 and PEP 12, Rust RFC template, KEP template, Go proposal README, RFC 7322, RFC 3552, Oxide RFD 1, Shape Up | What each genre requires: motivation, goals and non-goals, guide-level before reference-level explanation, drawbacks and alternatives, risks, unresolved questions, test plans; Shape Up's rough/solved/bounded level of detail and its rabbit holes and no-gos. |
| Analytic writing rubrics | AAC&U Written Communication VALUE rubric, 6+1 Traits | Trait-separated scoring: context and purpose, content development, genre conventions, evidence, organization, word choice, conventions. |
| Text organization research | Gopen and Swan, Minto, Halliday and Hasan, Grice | Reader expectations for progression (old before new, governing idea first), cohesion ties, and the maxims of quantity, quality, relation and manner. |
| Generated-text evaluation | SummEval, G-Eval, Prometheus, FActScore, SummaC, FactCC, QAGS, Coh-Metrix | Per-dimension judging with anchors and evidence before score; claim-level and entailment fidelity checks; automatic cohesion indices. |
| Judge reliability | MT-Bench, verbosity bias (Saito et al.), length-controlled AlpacaEval, Huang et al., Burrows's Delta | Position, length and self-preference biases; rubric-tuned judges that fail to generalise; stylometric distance for measuring style-match bias. |

## Derivation

A dimension was kept when at least two independent families name it as a distinct property a reviewer checks, and when it can fail while the others hold. That second condition is what the fixtures test: each pair changes one dimension and holds the rest.

- **Purpose, context and audience** is the AAC&U "context of and purpose for writing" criterion, ISO 24495 "relevant", and the motivation sections of every corpus template.
- **Fidelity** is ISO 29148 "correct" applied to a brief or prefix rather than to the world, and is what the summarisation consistency literature measures. The plan requires it to be judged alongside readability.
- **Requirement coverage** is set-level completeness (ISO 29148, INCOSE) together with traceability back to the request (Gotel and Finkelstein). It is distinct from fidelity: a document can be faithful in everything it says and still drop a requirement.
- **Scope and level of abstraction** combines the solution-free rule for requirements (INCOSE, NASA), Google's warning about implementation manuals, Shape Up's level of detail and RFC 4101. It fails in both directions, too concrete and too abstract.
- **Rationale and alternatives** is the ISO 42010 rationale requirement and the drawbacks, alternatives and rejected-ideas sections of the Rust, KEP, PEP and Google templates.
- **Organization and progression** is the 6+1 and AAC&U organization trait, given an operational form by Gopen and Swan, Minto, RFC 4101 and the Rust template's guide-level before reference-level ordering.
- **Concision** is Grice's quantity maxim and the plain-language rule to omit excess words. Write the Docs' ARID principle and the user's own criterion (useful elaboration is not a fault, see below) keep it from becoming a length penalty.
- **Clarity and precision** is ISO 29148 "unambiguous", the INCOSE vague-term rules and RFC 8174 keywords. It is separated from concision because a text can be short and vague.
- **Internal consistency** is ISO 29148 and INCOSE set consistency. It is separated from fidelity because the failure is within the document, with no input needed to detect it.
- **Risks, uncertainty and open questions** comes from KEP risks and mitigations, Rust unresolved questions, PEP open issues, Shape Up rabbit holes and no-gos, and RFC 3552.
- **Verifiability and success criteria** is ISO 29148 and INCOSE "verifiable" and the KEP test plan and graduation criteria. For PM plans it is the tests field.
- **Genre and template conformance** is AAC&U "genre and disciplinary conventions" made concrete by the corpus templates and, for PM plans, by the structure `pm_core/plans/parser.py` parses.
- **Continuity with the prefix** applies only to continuation cases. It is cohesion (Halliday and Hasan, Coh-Metrix) and the old-before-new expectation across the cut. It deliberately excludes stylistic resemblance, which plan-doc-eval flags as favouring the original author.

Sentence-level mechanics (AAC&U "control of syntax and mechanics", 6+1 "conventions") is folded into clarity rather than kept separate. Frontier-model output rarely fails it, and a separate score would mostly add noise. The 6+1 "voice" trait is not used: in reference-comparison cases, voice is where the original author's identity shows.

## The previously identified concerns

The four concerns raised during planning are placed within this set rather than treated as the measure. Fidelity is mapped the same way. The user's criterion, recorded in [plan-session-sources-2026-10-19.md](../../../pm/docs/plan-session-sources-2026-10-19.md), sets the boundary for all of them. Additional material not explicitly discussed is not automatically wrong. Obvious material, or text that adds no planning value, is a primary readability problem. Distracting material draws review away from important decisions. Whether distracting material impairs agent readers the way it impairs human reviewers is an open question.

| Concern | Primary dimension | Also affects | Boundary |
|---|---|---|---|
| Padding | concision | purpose_and_audience, organization_and_progression, continuity | Useful elaboration and genre-required length are not padding; judge density and relevance, not word count. |
| Premature implementation detail | scope_and_abstraction | rationale_and_alternatives, concision | Interfaces, schemas or protocols that are themselves under review, and detail the brief asks for, are not premature. |
| Poor progression | organization_and_progression | continuity | Summary-first order and genre-mandated order are not failures. |
| Lost requirements | requirement_coverage | fidelity, verifiability | A requirement deliberately deferred with a stated reason is not lost. |
| Fidelity | fidelity | internal_consistency, requirement_coverage | Consistent elaboration offered as the writer's proposal is not a fidelity failure. |

Each concern has at least one concern-tagged fixture. Lost requirements, for example, has `coverage_lost_requirement_plan` and `verifiability_vague_tests`.

## Judge templates

[templates/whole_document.md](templates/whole_document.md) shows the brief and two documents. [templates/continuation.md](templates/continuation.md) shows the prefix, the optional section request given to the generator, and two candidate next sections. Both follow the same contract:

- **Blinded pairs.** Candidates appear only as A and B. The templates take no origin, source, URL or provenance fields, and they tell the judge that order and labels carry no information. Randomising order and running swapped pairs is the runner's job.
- **One dimension at a time, evidence first.** This follows G-Eval and Prometheus. For each dimension the judge cites passages, then gives a 1–5 score per candidate against the anchors and a per-dimension preference. The overall preference is asked for separately and is never computed from the dimension scores, so disagreements between dimensions stay visible.
- **Bias instructions.** Length is not quality (verbosity bias). Consistent elaboration is not a fidelity fault. For continuations, a candidate is not rewarded for imitating the prefix author's style.
- **Track separation.** `render_judge()` lists only the dimensions that apply to the case type. Track notes tell continuation judges to measure coverage against what the prefix promised and fidelity against what the prefix established. The two tracks use different templates and are never pooled.
- **Output contract.** A JSON object with one row per dimension (`dimension`, `evidence`, `rationale`, `score_a`, `score_b`, `preference`), plus `overall_preference` and `overall_rationale`. `validate_judgment()` checks it, so the runner can treat a malformed reply as a failed evaluation rather than a score.

Render a fixture's prompt with `python3 rubric.py --render whole_document`, `--render continuation` or `--render <fixture id>`.

## What calibration must establish

The runner and calibration PR decides which of these measures are usable. For each dimension and case type it needs to report:

- Consistency across repeated judgments and across swapped order (position bias, MT-Bench).
- Agreement between frontier and JEV judges, and with automatic candidates where they exist.
- Sensitivity to length (the `length_ratio` covariate, length-controlled AlpacaEval), to formatting, to source identity and, for continuations, to style match (the `style_distance` covariate).
- Whether the fixtures come out in the expected direction on their target dimension without moving the other dimensions as much. This is the check that dimensions stay distinct. A judge that scores every dimension from one overall impression will fail it. Huang et al. find that fine-tuned judges generalise poorly beyond the evaluation scheme they were trained on, so this has to be checked for each judge.

Measures marked `deferred` need inference-engine access (classifier or NLI probabilities). Plan-doc-eval places them outside the first PRs.

## Fixtures

Each file in [fixtures/](fixtures/) holds a brief or prefix, a `strong` and a `weak` variant, the target `dimension`, any `concerns` it exercises, `held_constant` (what the pair keeps equal) and `notes` (what the weak variant breaks). The pairs are synthetic and short so that the difference is unambiguous. Lengths are matched except in the padding pairs, where the length difference is the point. Those pairs double as a verbosity-bias probe: a judge that prefers the padded variant is rewarding length.

## Limitations

The dimensions come from published guidance and are not yet validated against preferences on this corpus. Some, such as rationale and risks, matter more for design proposals than for reference documentation, and calibration may show they should be weighted or reported per document kind. The automatic candidates are specified here but not implemented. ISO, IEEE and INCOSE texts are cited from their published descriptions and public summaries, not from purchased full texts.

## Dimension reference

<!-- GENERATED: python3 rubric.py --write-doc -->
| Dimension | Case types | Readiness | Automatic candidates | Concerns |
|---|---|---|---|---|
| purpose_and_audience | whole_document, continuation | calibration_required | — | padding |
| fidelity | whole_document, continuation | calibration_required | — | fidelity, lost_requirements |
| requirement_coverage | whole_document, continuation | automatic_candidate | brief_item_lexical_recall, pm_plan_field_preservation | lost_requirements, fidelity |
| scope_and_abstraction | whole_document, continuation | automatic_candidate | implementation_token_density | premature_implementation_detail |
| rationale_and_alternatives | whole_document, continuation | calibration_required | — | premature_implementation_detail |
| organization_and_progression | whole_document, continuation | automatic_candidate | define_before_use, adjacent_section_overlap | poor_progression, padding |
| concision | whole_document, continuation | automatic_candidate | redundancy_rate, filler_lexicon_rate, length_ratio (bias covariate) | padding, premature_implementation_detail |
| clarity_and_precision | whole_document, continuation | automatic_candidate | vague_term_rate, undefined_acronyms | — |
| internal_consistency | whole_document, continuation | automatic_candidate | term_variant_detection, pm_dependency_agreement | fidelity |
| risks_and_open_questions | whole_document, continuation | calibration_required | — | — |
| verifiability | whole_document, continuation | automatic_candidate | pm_tests_field_present | lost_requirements |
| genre_conventions | whole_document, continuation | automatic_candidate | template_section_presence, pm_plan_parse | — |
| continuity | continuation | automatic_candidate | prefix_repetition, established_term_reuse, style_distance (bias covariate) | poor_progression, padding |

### purpose_and_audience — Purpose, context and audience

**Definition.** The document states what problem it addresses, why now, for whom, and what decision or action it asks of the reader, and its content is selected for that reader's needs.

**Continuation.** The section serves the purpose the prefix has established and the role the section's position implies; it does not re-introduce the document's purpose.

**Derived from.** AAC&U 'context of and purpose for writing'; ISO 24495 'relevant'; PEP motivation, KEP motivation/goals, Shape Up problem and appetite, Google 'context and scope'; Grice's maxim of relation.

**Sources.** [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication); [ISO 24495-1:2023 Plain language — Part 1: Governing principles and guidelines](https://www.iso.org/standard/78907.html); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [Shape Up, Chapter 6: Write the Pitch (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.5-chapter-06); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/); [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003)

**Detection guidance.**

- Can a reader state the problem, the intended reader and the requested decision after the first screen?
- Is there material that serves no identifiable reader need (history of the author's process, general tutorials, marketing)?
- Does the document address a different problem than the brief asks for, or a generic version of it?

**Not a fault.**

- A short motivation when the brief already establishes shared context.
- Background that a reviewer needs to evaluate the decision.

**Example, stronger.** Reviewers currently cannot tell which PRs are blocked by an unmerged dependency. This plan adds a merge wait so autostart holds dependents until their dependencies merge; it asks reviewers to accept the hold semantics in section 2.

**Example, weaker.** Project management is an important part of software engineering. Teams use many tools to organize work. This document describes some improvements.

**Score anchors.** 1: Purpose absent or wrong; content generic or aimed at no identifiable reader. 3: Purpose recoverable but late or vague; some content serves no reader need. 5: Problem, reader and requested decision clear early; content consistently selected for that reader.

**Candidate measures** (readiness: calibration_required).

- `judge_purpose` (judge, needs_calibration): Rubric judge score and paired preference on this dimension.

**Fixtures.** `fixtures/purpose_generic_intro.json`

### fidelity — Fidelity to brief or prefix

**Definition.** Every claim, decision and constraint the document attributes to the brief (or, for continuations, to the prefix) is supported by it and none contradicts it; elaboration beyond the input is consistent with it and recognisable as the writer's proposal rather than presented as agreed fact.

**Continuation.** Judge against the prefix: no contradiction of decisions, names, numbers or scope established earlier in the document.

**Derived from.** ISO 29148 'correct'; summarisation consistency literature (FActScore atomic claims, SummaC/FactCC entailment, QAGS question answering, SummEval 'consistency'); Grice's maxim of quality.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [Min, S. et al. FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation](https://arxiv.org/abs/2305.14251); [Laban, P. et al. SummaC: Re-Visiting NLI-based Models for Inconsistency Detection in Summarization. TACL 10](https://arxiv.org/abs/2111.09525); [Kryściński, W. et al. Evaluating the Factual Consistency of Abstractive Text Summarization. EMNLP](https://arxiv.org/abs/1910.12840); [Wang, A., Cho, K. and Lewis, M. Asking and Answering Questions to Evaluate the Factual Consistency of Summaries. ACL](https://arxiv.org/abs/2004.04228); [Fabbri, A. R. et al. SummEval: Re-evaluating Summarization Evaluation. TACL 9](https://arxiv.org/abs/2007.12626); [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003)

**Detection guidance.**

- Split the document into atomic claims; for each claim that refers to the input, check that the input supports it.
- Flag numbers, names, identifiers, dates and owners that do not appear in the input and are stated as given rather than proposed.
- Flag reversals: a constraint from the input stated with the opposite polarity or a weakened obligation (MUST to SHOULD).
- For PM plans, flag decisions attributed to the human that the conversation shows the assistant proposed and the human did not accept.

**Not a fault.**

- Useful elaboration, reasoning or design detail that is consistent with the input, even when the input never mentions it.
- Explicitly marked proposals or assumptions.

**Example, stronger.** The brief requires a 30-day retention window. This design keeps 30 days; we also propose compacting entries older than 7 days, which the brief does not address.

**Example, weaker.** As agreed, retention is 14 days and compaction is mandatory for all tenants.

**Score anchors.** 1: Contradicts the input on a material point or invents agreed decisions. 3: No material contradiction, but some unsupported specifics are stated as given. 5: All input-attributed content supported; elaboration consistent and clearly the writer's proposal.

**Candidate measures** (readiness: calibration_required).

- `judge_fidelity` (judge, needs_calibration): Rubric judge with the brief or prefix in view; must quote the conflicting passages.
- `atomic_claim_support` (model_assisted, needs_calibration): FActScore-style: a prompted model decomposes the draft into input-referring claims and labels each supported/contradicted/unsupported against the input.
- `nli_consistency` (model_assisted, deferred): SummaC-style sentence-pair entailment between input and draft using an NLI classifier's probabilities.

**Fixtures.** `fixtures/fidelity_brief_contradiction.json`, `fixtures/fidelity_prefix_contradiction.json`

### requirement_coverage — Requirement coverage and traceability

**Definition.** Every requirement, constraint, scope decision and open question in the brief is carried into the document where a reader would look for it, so each can be traced back to its source.

**Continuation.** Coverage is measured against commitments the prefix makes for this section (announced topics, promised details, 'see section N'), not against a brief.

**Derived from.** ISO 29148 and INCOSE set-level completeness; requirements traceability (Gotel and Finkelstein pre-requirements traceability); NASA requirement traceability; QAGS-style question answering adapted from summaries to briefs.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [Gotel, O. and Finkelstein, A. An Analysis of the Requirements Traceability Problem. Proc. IEEE ICRE, 94–101](https://ieeexplore.ieee.org/document/292398); [NASA Systems Engineering Handbook (NASA/SP-2016-6105 Rev 2)](https://www.nasa.gov/reference/systems-engineering-handbook/); [Wang, A., Cho, K. and Lewis, M. Asking and Answering Questions to Evaluate the Factual Consistency of Summaries. ACL](https://arxiv.org/abs/2004.04228)

**Detection guidance.**

- List the brief's requirements, constraints, non-goals and explicit questions; locate each in the document.
- A requirement is lost when it is absent, merged into a broader statement that no longer implies it, or moved to a place where the reader of that part would not find it (for PM plans: stated in the intro but absent from the PR that must implement it).
- For continuations, list what the prefix promised this section would cover and check each.

**Not a fault.**

- Requirements consolidated into one statement that still implies each.
- A requirement deliberately deferred with a stated reason.

**Example, stronger.** PR 2 tests: verify that dependents stay held while any dependency is unmerged, including when the dependency is edited mid-run (brief item 3).

**Example, weaker.** PR 2 tests: verify the merge wait works.

**Score anchors.** 1: Several explicit requirements missing or diluted beyond recognition. 3: Most present; one material requirement missing, diluted or misplaced. 5: Every requirement traceable to an appropriate place in the document.

**Candidate measures** (readiness: automatic_candidate).

- `judge_coverage` (judge, needs_calibration): Rubric judge lists brief items and marks each covered/diluted/missing.
- `brief_item_lexical_recall` (deterministic, automatic_candidate): Split the brief into items (list entries, sentences with obligation words); for each item compute content-word recall in the best-matching document paragraph; report items under a threshold. Paraphrase defeats it, so it flags rather than scores.
- `pm_plan_field_preservation` (deterministic, automatic_candidate): For PM plan cases, parse PR blocks with pm_core.plans.parser.parse_plan_prs and check that titles and depends_on named in the conversation's accepted structure survive.
- `brief_question_answering` (model_assisted, needs_calibration): QAGS-style: generate questions from the brief, answer them from the draft only, compare with answers from the brief.

**Fixtures.** `fixtures/coverage_lost_requirement_plan.json`

### scope_and_abstraction — Scope and level of abstraction

**Definition.** The document works at the level of detail its kind and stage call for: it fixes the decisions a reader must review now, states goals and non-goals, and leaves implementation choices that do not affect those decisions to the people who implement them.

**Continuation.** The section's level of detail matches the prefix's and the section's role; a reference-level section may be detailed where an overview section may not.

**Derived from.** ISO 29148 and INCOSE 'appropriate' level and solution-free requirements; NASA implementation-free requirements; Google design docs ('really implementation manuals'); Shape Up 'rough, solved, bounded' (wireframes too concrete, words too abstract); RFC 4101 detail for implementors gets in the way of review; KEP goals/non-goals; Diátaxis separation of purposes.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/); [Shape Up, Principles of Shaping (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.1-chapter-02); [RFC 4101 — Writing Protocol Models (E. Rescorla)](https://www.rfc-editor.org/rfc/rfc4101); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [NASA Systems Engineering Handbook (NASA/SP-2016-6105 Rev 2)](https://www.nasa.gov/reference/systems-engineering-handbook/); [Diátaxis: a systematic approach to technical documentation authoring (D. Procida)](https://diataxis.fr/)

**Detection guidance.**

- Mark passages that fix function names, file layouts, data-structure fields, flags or step-by-step code changes; ask whether any reviewed decision depends on them.
- Premature implementation detail is detail that constrains implementers without a reason the document states, or that buries the decisions under it.
- The opposite failure also counts: so abstract that no decision is made (words too abstract).
- Check for explicit non-goals or boundaries.

**Not a fault.**

- Interface, schema or protocol detail that is itself the decision under review.
- Detail the brief explicitly requests.
- Reference-level sections in genres that require them (PEP specification, RFC protocol detail).

**Example, stronger.** Holds are derived from dependency state at read time rather than stored, so an edited dependency graph takes effect without migration. Non-goal: changing how merges themselves are detected.

**Example, weaker.** Add a function _compute_holds(self, prs: list[dict]) -> set[str] in pm_core/tui/auto_start.py after line 212, iterate with a for loop, and store results in self._hold_cache.

**Score anchors.** 1: Mostly implementation steps or so abstract that nothing is decided. 3: Right level overall with notable stretches of unmotivated implementation detail or vagueness. 5: Detail tracks the decisions; boundaries and non-goals explicit.

**Candidate measures** (readiness: automatic_candidate).

- `judge_abstraction` (judge, needs_calibration): Rubric judge; must cite the passages it considers premature.
- `implementation_token_density` (deterministic, automatic_candidate): Share of tokens inside code spans/blocks plus identifiers, file paths, line numbers and signatures per 1000 words, compared with the reference distribution for the same document kind.

**Fixtures.** `fixtures/scope_premature_impl_design.json`

### rationale_and_alternatives — Rationale, trade-offs and alternatives

**Definition.** Decisions come with the reasons for them, the trade-offs accepted and the credible alternatives rejected, so a reviewer can disagree with a specific step rather than with the whole.

**Continuation.** Applies when the section makes or defends decisions; a purely descriptive section is judged on whether it supports decisions made elsewhere.

**Derived from.** ISO 42010 decision rationale; Rust RFC 'drawbacks' and 'rationale and alternatives'; PEP rationale and rejected ideas; Google 'alternatives considered'; KEP alternatives; NASA trade studies; AAC&U 'sources and evidence'.

**Sources.** [ISO/IEC/IEEE 42010:2022 Software, systems and enterprise — Architecture description](https://www.iso.org/standard/74393.html); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [NASA Systems Engineering Handbook (NASA/SP-2016-6105 Rev 2)](https://www.nasa.gov/reference/systems-engineering-handbook/); [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication)

**Detection guidance.**

- For each consequential decision, look for a reason tied to a goal or constraint.
- Check that rejected alternatives are ones a knowledgeable reviewer would raise, and that the reason for rejection is specific.
- Flag straw-man alternatives and rationale that only restates the decision.

**Not a fault.**

- Decisions the brief already settled, cited rather than re-argued.

**Example, stronger.** We derive holds at read time instead of storing them: stored holds would need invalidation on every graph edit, which is where the previous design lost holds. The cost is a recomputation per poll, measured at under 1 ms for 500 PRs.

**Example, weaker.** We derive holds at read time because it is the best approach.

**Score anchors.** 1: Decisions asserted without reasons. 3: Reasons for main decisions; trade-offs or alternatives thin or straw-man. 5: Each consequential decision has specific reasons, accepted costs and credible alternatives.

**Candidate measures** (readiness: calibration_required).

- `judge_rationale` (judge, needs_calibration): Rubric judge score and paired preference.

**Fixtures.** `fixtures/rationale_missing_tradeoffs.json`

### organization_and_progression — Organization and progression

**Definition.** The document moves from context to decision to detail in an order a reader can follow: overview before specifics, terms defined before use, dependencies before what depends on them, and each part building on what came before.

**Continuation.** The section advances from where the prefix stopped rather than restarting, looping back or jumping ahead of material the prefix has not yet introduced.

**Derived from.** Gopen and Swan reader expectations (old before new, stress position); Minto governing idea first; RFC 4101 model before detail; Rust RFC guide-level before reference-level; 6+1 'organization'; AAC&U 'content development'; plain-language 'organize to meet readers' needs'; GOV.UK front-loading; Coh-Metrix cohesion.

**Sources.** [Gopen, G. D. and Swan, J. A. The Science of Scientific Writing. American Scientist 78(6):550–558](https://www.americanscientist.org/blog/the-long-view/the-science-of-scientific-writing); [Minto, B. The Pyramid Principle: Logic in Writing and Thinking (3rd ed.). Pearson](https://www.barbaraminto.com/); [RFC 4101 — Writing Protocol Models (E. Rescorla)](https://www.rfc-editor.org/rfc/rfc4101); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [6+1 Trait Writing model (Education Northwest)](https://educationnorthwest.org/traits); [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [GOV.UK content design: writing for GOV.UK](https://www.gov.uk/guidance/content-design/writing-for-gov-uk); [Graesser, A. C., McNamara, D. S., Louwerse, M. M. and Cai, Z. Coh-Metrix: Analysis of text on cohesion and language. Behavior Research Methods 36:193–202](https://doi.org/10.3758/BF03195564)

**Detection guidance.**

- Read only headings and first sentences: do they tell the argument in order?
- Flag terms, components or PRs used before they are introduced, and conclusions that appear before the material supporting them without signposting.
- Flag sections whose order would have to change for the dependencies among them to make sense (for PM plans, a PR described before the PRs it depends on without reason).
- Flag repeated returns to the same topic in separate places.

**Not a fault.**

- A summary-first structure that states conclusions up front by design (pyramid order).
- Genre-mandated section order.

**Example, stronger.** Section 1 states the hold rule; section 2 shows how holds are derived from dependency state; section 3 covers edits to the graph while holds are active.

**Example, weaker.** Section 1 describes cache invalidation on graph edits; section 2 introduces the hold rule that section 1 relied on; section 3 returns to the cache.

**Score anchors.** 1: Order obstructs understanding; frequent use-before-introduction or loops. 3: Generally ordered with some jumps, forward references or repeated returns. 5: Clear progression; headings alone tell the argument.

**Candidate measures** (readiness: automatic_candidate).

- `judge_progression` (judge, needs_calibration): Rubric judge score and paired preference.
- `define_before_use` (deterministic, automatic_candidate): Acronyms and capitalised/coded terms whose first occurrence is not a definition pattern (expansion, 'X is', 'we call') but whose defining occurrence appears later.
- `adjacent_section_overlap` (deterministic, automatic_candidate): Coh-Metrix-style content-word overlap between adjacent sections versus non-adjacent ones; low adjacency relative to the reference flags jumps.

**Fixtures.** `fixtures/progression_poor_order.json`

### concision — Concision and information density

**Definition.** Each passage adds information the reader needs; the document omits filler, restatement, obvious material and generic advice that would hold for any project, while keeping elaboration and repetition that help the reader.

**Continuation.** Judge filler and restatement within the section; repetition of the prefix itself is scored under continuity, not here.

**Derived from.** Grice's maxim of quantity; plain-language 'omit excess words'; Williams on redundant and implied words; Microsoft 'get to the point fast'; Write the Docs ARID as the counterweight (useful repetition is allowed); verbosity-bias literature for the judge-side risk.

**Sources.** [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [Williams, J. M. and Bizup, J. Style: Lessons in Clarity and Grace (12th ed.). Pearson](https://www.pearson.com/en-us/subject-catalog/p/style-lessons-in-clarity-and-grace/P200000003473); [Microsoft Writing Style Guide](https://learn.microsoft.com/en-us/style-guide/welcome/); [Google developer documentation style guide](https://developers.google.com/style); [Write the Docs: Documentation principles](https://www.writethedocs.org/guide/writing/docs-principles/); [Saito, K. et al. Verbosity Bias in Preference Labeling by Large Language Models](https://arxiv.org/abs/2310.10076); [Dubois, Y. et al. Length-Controlled AlpacaEval: A Simple Way to Debias Automatic Evaluators](https://arxiv.org/abs/2404.04475)

**Detection guidance.**

- For each paragraph ask: would a reader of this document lose anything if it were deleted?
- Flag generic statements true of any project ("testing is important"), restatements of the previous paragraph, summaries of summaries, and hedging chains.
- Distracting material also counts: content that draws a reviewer's attention away from the decisions that need review.
- Judge density, not length: a long document can be concise and a short one padded.

**Not a fault.**

- Useful elaboration, examples and reasoning beyond the brief.
- Deliberate repetition for skimmability (a one-line summary at the top of a long section).
- Length the genre requires.

**Example, stronger.** Dependents stay held until every dependency merges; a dependency edited while held re-evaluates on the next poll.

**Example, weaker.** It is important to note that dependencies matter. As we have discussed above, dependents should, in general, wait for their dependencies. In other words, a dependent PR should not start before its dependencies are merged, which, as mentioned, is key.

**Score anchors.** 1: Much of the text is filler, restatement or generic advice. 3: Mostly informative with noticeable padding in places. 5: Dense with needed information; elaboration earns its place.

**Candidate measures** (readiness: automatic_candidate).

- `judge_concision` (judge, needs_calibration): Rubric judge; must point to deletable passages. Calibration must check length sensitivity (verbosity bias) explicitly.
- `redundancy_rate` (deterministic, automatic_candidate): Share of content-word 4-grams that repeat across paragraphs, after removing headings and quoted input.
- `filler_lexicon_rate` (deterministic, automatic_candidate): Vale-style lexicon of filler and throat-clearing phrases ('it is important to note', 'as mentioned above', 'in other words') per 1000 words.
- `length_ratio` (deterministic, automatic_candidate, bias covariate): Draft length over reference length; recorded to measure judge length sensitivity, never scored as quality.

**Fixtures.** `fixtures/concision_padding_continuation.json`, `fixtures/concision_padding_plan.json`

### clarity_and_precision — Clarity and precision

**Definition.** Statements have one reasonable reading: obligations are explicit, quantities and conditions are specific, terms are defined and used consistently, and sentences are readable for the intended audience.

**Continuation.** Terms the prefix defined are used with the same meaning.

**Derived from.** ISO 29148 'unambiguous'; INCOSE rules against vague terms, escape clauses and open-ended lists; RFC 8174 requirement keywords; RFC 7322 editorial clarity; Google style; ISO 24495 'understandable'; 6+1 'word choice' and 'conventions'; AAC&U 'control of syntax and mechanics'.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words](https://www.rfc-editor.org/rfc/rfc8174); [RFC 7322 — RFC Style Guide](https://www.rfc-editor.org/rfc/rfc7322); [Google developer documentation style guide](https://developers.google.com/style); [ISO 24495-1:2023 Plain language — Part 1: Governing principles and guidelines](https://www.iso.org/standard/78907.html); [6+1 Trait Writing model (Education Northwest)](https://educationnorthwest.org/traits); [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication)

**Detection guidance.**

- Flag vague qualifiers (appropriate, as needed, fast, robust, user-friendly, etc., and/or) where a reviewer needs a specific value or condition.
- Flag obligations whose force is unclear (should vs must) when it matters.
- Flag pronouns or 'this' with more than one plausible referent, and undefined acronyms.

**Not a fault.**

- Deliberate openness that is labelled as an open question.

**Example, stronger.** The hold MUST be released within one poll interval (default 2 s) after the last dependency merges.

**Example, weaker.** The hold should be released quickly and appropriately once things are merged.

**Score anchors.** 1: Key statements ambiguous; obligations and conditions vague. 3: Mostly clear; some vague qualifiers or unclear obligations on material points. 5: Precise throughout where precision matters.

**Candidate measures** (readiness: automatic_candidate).

- `judge_clarity` (judge, needs_calibration): Rubric judge score and paired preference.
- `vague_term_rate` (deterministic, automatic_candidate): INCOSE-derived lexicon of vague and escape-clause terms per 1000 words.
- `undefined_acronyms` (deterministic, automatic_candidate): Acronyms never expanded in the document or input.

**Fixtures.** `fixtures/clarity_vague_requirements.json`

### internal_consistency — Internal consistency

**Definition.** The document does not contradict itself: names, numbers, scope, decisions and dependency statements agree across sections.

**Continuation.** Consistency within the section and with the prefix overlaps fidelity; record contradictions of the prefix under fidelity and contradictions inside the new section here.

**Derived from.** ISO 29148 and INCOSE set-level consistency; RFC 7322 consistent terminology; SummEval 'consistency' adapted to self-consistency.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [RFC 7322 — RFC Style Guide](https://www.rfc-editor.org/rfc/rfc7322); [Fabbri, A. R. et al. SummEval: Re-evaluating Summarization Evaluation. TACL 9](https://arxiv.org/abs/2007.12626)

**Detection guidance.**

- Collect every stated value, name and decision that appears more than once and compare occurrences.
- For PM plans, check that dependencies stated in prose match depends_on fields and that a PR is not both in and out of scope.
- Flag one concept named several ways when readers could take them as different things.

**Not a fault.**

- A value changed with an explicit note ("revised from 30 to 14 days after section 4").

**Example, stronger.** Section 2 and the PR list both state that the runner depends on the rubric and the case catalog.

**Example, weaker.** Section 2 says the runner needs only the rubric; the PR list makes it depend on the case catalog as well.

**Score anchors.** 1: Material contradictions between sections. 3: Minor inconsistencies in naming or secondary values. 5: Fully consistent.

**Candidate measures** (readiness: automatic_candidate).

- `judge_consistency` (judge, needs_calibration): Rubric judge; must quote both sides of each contradiction.
- `term_variant_detection` (deterministic, automatic_candidate): Near-duplicate identifiers and terms (case, hyphenation, pluralisation, edit distance) used for what may be one concept.
- `pm_dependency_agreement` (deterministic, automatic_candidate): For PM plans, depends_on entries resolve to PR titles in the same plan (pm_core.plans.parser.parse_plan_prs).

**Fixtures.** `fixtures/consistency_dependency_mismatch.json`

### risks_and_open_questions — Risks, uncertainty and open questions

**Definition.** The document states what could go wrong, what is unknown, which questions remain for reviewers and what is deliberately excluded, instead of presenting an uncertain plan as settled.

**Continuation.** Applies when the section's role includes risks or unresolved questions, or when it makes claims whose uncertainty the prefix has flagged.

**Derived from.** KEP risks and mitigations; Rust unresolved questions; PEP open issues and security implications; Shape Up rabbit holes and no-gos; RFC 3552 security considerations; Oxide RFD discussion states; Google cross-cutting concerns.

**Sources.** [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [Shape Up, Chapter 6: Write the Pitch (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.5-chapter-06); [RFC 3552 — Guidelines for Writing RFC Text on Security Considerations](https://www.rfc-editor.org/rfc/rfc3552); [Oxide RFD 1 — Requests for Discussion](https://rfd.shared.oxide.computer/rfd/0001); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/)

**Detection guidance.**

- Look for named risks with consequences and mitigations, not a generic 'risks: bugs may occur'.
- Check that genuinely unknown things are marked as unknown and that exclusions are explicit.
- Flag false certainty: claims about performance, adoption or compatibility without evidence or caveat.

**Not a fault.**

- A short or empty risks section for a small, low-risk change, if it says so.

**Example, stronger.** Risk: a dependency closed without merging would hold dependents forever. Mitigation: treat closed-unmerged as released and log it. Open question for reviewers: should a reopened dependency re-hold started dependents?

**Example, weaker.** Risks: there may be some edge cases, which will be handled during implementation.

**Score anchors.** 1: No risks or open questions where clearly needed; false certainty. 3: Some specific risks; others generic or missing. 5: Specific risks with mitigations, explicit unknowns and exclusions.

**Candidate measures** (readiness: calibration_required).

- `judge_risks` (judge, needs_calibration): Rubric judge score and paired preference.

**Fixtures.** `fixtures/risks_false_certainty.json`

### verifiability — Verifiability and success criteria

**Definition.** The document says how anyone will know it succeeded: requirements are testable, acceptance and test plans are concrete, and milestones or graduation criteria are checkable.

**Continuation.** Applies to sections that state requirements, tests or milestones.

**Derived from.** ISO 29148 and INCOSE 'verifiable'; NASA requirement verification; KEP test plan and graduation criteria; RFC 8174 requirement keywords as testable obligations.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [NASA Systems Engineering Handbook (NASA/SP-2016-6105 Rev 2)](https://www.nasa.gov/reference/systems-engineering-handbook/); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words](https://www.rfc-editor.org/rfc/rfc8174)

**Detection guidance.**

- For each requirement or PR, ask what observation would show it is met.
- Flag tests that restate the feature ('verify it works'), unmeasurable criteria and missing failure cases.
- For PM plans, each PR's tests field names concrete behaviours, including the failure and concurrency cases the description implies.

**Not a fault.**

- Exploratory documents (early RFDs, pitches) that state what evidence would settle a question rather than full acceptance tests.

**Example, stronger.** Tests: a dependent stays held while its dependency is open; it starts within one poll after merge; a closed-unmerged dependency releases it with a log line.

**Example, weaker.** Tests: test the merge wait thoroughly.

**Score anchors.** 1: No checkable criteria. 3: Some concrete tests; key requirements lack checks. 5: Every material requirement has a concrete check, including failure cases.

**Candidate measures** (readiness: automatic_candidate).

- `judge_verifiability` (judge, needs_calibration): Rubric judge score and paired preference.
- `pm_tests_field_present` (deterministic, automatic_candidate): For PM plans, share of PR blocks with a non-empty tests field that names more than restated feature words (content-word overlap with the description below a threshold).

**Fixtures.** `fixtures/verifiability_vague_tests.json`

### genre_conventions — Genre and template conformance

**Definition.** The document follows the conventions of its kind that readers and tools rely on: required sections and fields, header metadata, section order and machine-readable structure (for PM plans, PR blocks with description, tests, files and depends_on).

**Continuation.** The section has the heading level, numbering and structural conventions the prefix establishes.

**Derived from.** AAC&U 'genre and disciplinary conventions'; the corpus's own templates (PEP 1/12, Rust RFC, KEP, Go proposals, RFC 7322, Shape Up); Diátaxis on keeping document kinds distinct.

**Sources.** [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [PEP 12 — Sample reStructuredText PEP Template](https://peps.python.org/pep-0012/); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [Go proposal process (golang/proposal README)](https://github.com/golang/proposal/blob/master/README.md); [RFC 7322 — RFC Style Guide](https://www.rfc-editor.org/rfc/rfc7322); [Shape Up, Chapter 6: Write the Pitch (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.5-chapter-06); [Diátaxis: a systematic approach to technical documentation authoring (D. Procida)](https://diataxis.fr/)

**Detection guidance.**

- Compare the section list with the template of the document kind; missing required sections count, optional ones do not.
- For PM plans, every PR block parses and carries description, tests, files and depends_on; dependency names match PR titles.
- Flag structure borrowed from another genre that misleads (a design doc formatted as a tutorial).

**Not a fault.**

- Merged or renamed sections that keep the content the template asks for.
- Brief instructions that override the template.

**Example, stronger.** ### PR: Rubric - **description**: ... - **tests**: ... - **files**: ... - **depends_on**:

**Example, weaker.** PR 2 - rubric (do this after the catalog): write the rubric and test it.

**Score anchors.** 1: Required structure missing; tools or readers relying on it would fail. 3: Mostly conformant; some required fields or sections missing. 5: Fully conformant, with deviations only where they serve the reader.

**Candidate measures** (readiness: automatic_candidate).

- `judge_genre` (judge, needs_calibration): Rubric judge score and paired preference.
- `template_section_presence` (deterministic, automatic_candidate): Required-section checklist per document_kind (from the process templates in references.json), heading-matched with synonyms.
- `pm_plan_parse` (deterministic, automatic_candidate): pm_core.plans.parser.parse_plan_prs returns at least one PR, every PR has non-empty description/tests/files, and depends_on resolves.

**Fixtures.** `fixtures/genre_pm_plan_fields.json`

### continuity — Continuity with the prefix

**Definition.** The new section continues the document the prefix began: it picks up where the prefix stopped, uses the prefix's established terms, decisions and structure, does not repeat material the prefix already covered, and does not jump past material the next section would need to introduce.

**Derived from.** Halliday and Hasan cohesion ties; Coh-Metrix referential overlap; Gopen and Swan old-before-new; stylometry (Burrows's Delta) and judge self-preference findings for the bias this dimension must exclude.

**Sources.** [Halliday, M. A. K. and Hasan, R. Cohesion in English. Longman](https://doi.org/10.4324/9781315836010); [Graesser, A. C., McNamara, D. S., Louwerse, M. M. and Cai, Z. Coh-Metrix: Analysis of text on cohesion and language. Behavior Research Methods 36:193–202](https://doi.org/10.3758/BF03195564); [Gopen, G. D. and Swan, J. A. The Science of Scientific Writing. American Scientist 78(6):550–558](https://www.americanscientist.org/blog/the-long-view/the-science-of-scientific-writing); [Burrows, J. 'Delta': a Measure of Stylistic Difference and a Guide to Likely Authorship. Literary and Linguistic Computing 17(3):267–287](https://doi.org/10.1093/llc/17.3.267); [Zheng, L. et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS Datasets and Benchmarks](https://arxiv.org/abs/2306.05685)

**Detection guidance.**

- Check that the first paragraph connects to the end of the prefix and that the section fills the role its position implies.
- Flag re-introductions of the document's purpose, redefinitions of established terms and content duplicated from the prefix. Contradictions of prefix decisions are scored under fidelity, not here.
- Do not reward matching the prefix author's idiosyncratic style (sentence rhythm, favourite words, punctuation habits): that favours the original author and is measured as a bias, not scored as quality.

**Not a fault.**

- A different but clear writing style.
- A short bridge sentence that recalls a point from much earlier in the prefix.

**Example, stronger.** With the hold rule from section 2 in place, graph edits need only one addition: a hold re-evaluates whenever its dependency set changes.

**Example, weaker.** This document describes a merge-wait feature for autostart. Autostart is a feature that starts PRs automatically.

**Score anchors.** 1: Restarts or repeats the prefix, or ignores the terms and decisions it established. 3: Continues but with some repetition, redefinition or a gap. 5: Seamless continuation in content and structure.

**Candidate measures** (readiness: automatic_candidate).

- `judge_continuity` (judge, needs_calibration): Rubric judge with the prefix in view; calibration must report sensitivity to style match separately.
- `prefix_repetition` (deterministic, automatic_candidate): Share of content-word 5-grams in the section that also occur in the prefix.
- `established_term_reuse` (deterministic, automatic_candidate): Of terms defined or emphasised in the prefix that the section's topic needs, share used verbatim rather than renamed.
- `style_distance` (deterministic, automatic_candidate, bias covariate): Burrows's Delta between prefix and section; recorded to measure how much judges reward style match, never scored as quality.

**Fixtures.** `fixtures/continuity_restart.json`
<!-- END GENERATED -->

## References

See [references.json](references.json) for full citations, URLs and what each source was used for.
