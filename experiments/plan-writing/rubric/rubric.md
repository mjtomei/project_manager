# Technical document quality rubric

Rubric for [pm/plans/plan-doc-eval.md](../../../pm/plans/plan-doc-eval.md): the quality dimensions that judges score whole-document and continuation cases on, where each comes from, how to detect it, and which measures are ready for use. It covers plans, design documents and specifications, and also reports about existing work, such as architecture digests and sign-off or QA reports written for a reader who does not read the code. The machine-readable source is [dimensions.json](dimensions.json) with the bibliography in [references.json](references.json); the dimension reference below is generated from them. Judge prompts, paired or single-document, are rendered from [templates/](templates/) by [rubric.py](../rubric.py). [fixtures/](fixtures/) holds published strong and weak pairs for each dimension, and every example and fixture text is quoted from a cited source rather than written for the rubric.

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
| Text organization research | Gopen and Swan, Minto, Halliday and Hasan, Barzilay and Lapata, Grice | Reader expectations for progression (old before new, governing idea first), cohesion ties, the entity-grid model of local coherence, and the maxims of quantity, quality, relation and manner. |
| Analytic tradecraft | ICD 203, Kent's words of estimative probability, IPCC uncertainty guidance, DA PAM 600-67 | Reports that state the bottom line first, separate information from assumptions and judgments, and express uncertainty in calibrated terms. |
| Generated-text evaluation | SummEval, G-Eval, Prometheus, FActScore, SummaC, FactCC, QAGS, Coh-Metrix | Per-dimension judging with anchors and evidence before score; claim-level and entailment fidelity checks; automatic cohesion indices. |
| Judge reliability | MT-Bench, verbosity bias (Saito et al.), length-controlled AlpacaEval, format bias (Zhang et al.), Huang et al., Burrows's Delta | Position, length, formatting and self-preference biases; rubric-tuned judges that fail to generalise; stylometric distance for measuring style-match bias. |
| Published examples | SEC Plain English Handbook, Google Technical Writing One and Two, Federal Plain Language Guidelines, UNC Writing Center, DA PAM 600-67, Berry et al., verified IETF errata, reviewed revisions of PEPs, Rust RFCs, KEPs and Internet-Drafts, XSum hallucination annotations, Go release notes | Before/after rewrites, corrections and annotated summaries that the examples and fixtures quote. They show each dimension in text someone else wrote and someone else judged. |

## Derivation

A dimension was kept when at least two independent families name it as a distinct property a reviewer checks, and when it can fail while the others hold. That second condition is what the fixtures test: each pair changes one dimension and holds the rest.

- **Purpose, context and audience** is the AAC&U "context of and purpose for writing" criterion, ISO 24495 "relevant", and the motivation sections of every corpus template.
- **Salience and synthesis** is SummEval "relevance" (selecting the important content), Minto's governing thought, the Army's bottom line up front and GOV.UK front-loading. It is separate from purpose, which asks whether the document has a reader and a request at all, and from concision, which asks whether text can be deleted: a document can be dense and well aimed and still bury its core constraint under detail or never say what its facts add up to.
- **Fidelity** is ISO 29148 "correct" applied to a brief, prefix or, for reports, the material the report describes rather than to the world, and is what the summarisation consistency literature measures. The plan requires it to be judged alongside readability.
- **Requirement coverage** is set-level completeness (ISO 29148, INCOSE) together with traceability back to the request (Gotel and Finkelstein). It is distinct from fidelity: a document can be faithful in everything it says and still drop a requirement.
- **Scope and level of abstraction** combines the solution-free rule for requirements (INCOSE, NASA), Google's warning about implementation manuals, Shape Up's level of detail and RFC 4101. It fails in both directions, too concrete and too abstract.
- **Rationale and alternatives** is the ISO 42010 rationale requirement and the drawbacks, alternatives and rejected-ideas sections of the Rust, KEP, PEP and Google templates.
- **Organization and progression** is the 6+1 and AAC&U organization trait, given an operational form by Gopen and Swan, Minto, RFC 4101 and the Rust template's guide-level before reference-level ordering. It reaches down to sentences (each picks up from the one before, as in Gopen and Swan and the entity-grid model) and covers formatting that cuts the links between connected ideas, such as a wall of bullets.
- **Concision** is Grice's quantity maxim and the plain-language rule to omit excess words. Write the Docs' ARID principle and the user's own criterion (useful elaboration is not a fault, see below) keep it from becoming a length penalty.
- **Clarity and precision** is ISO 29148 "unambiguous", the INCOSE vague-term rules and RFC 8174 keywords. It is separated from concision because a text can be short and vague.
- **Internal consistency** is ISO 29148 and INCOSE set consistency. It is separated from fidelity because the failure is within the document, with no input needed to detect it.
- **Risks, uncertainty and open questions** comes from KEP risks and mitigations, Rust unresolved questions, PEP open issues, Shape Up rabbit holes, and RFC 3552. Exclusions and no-gos belong to scope, which owns non-goals. For reports it also covers epistemic status, from ICD 203 and the estimative-language literature: claims carry the confidence their evidence supports, and what was verified is told apart from what is inferred.
- **Verifiability and success criteria** is ISO 29148 and INCOSE "verifiable" and the KEP test plan and graduation criteria. For PM plans it is the tests field.
- **Genre and template conformance** is AAC&U "genre and disciplinary conventions" made concrete by the corpus templates and, for PM plans, by the structure `pm_core/plans/parser.py` parses.
- **Continuity with the prefix** applies only to continuation cases. It is cohesion (Halliday and Hasan, Coh-Metrix) and the old-before-new expectation across the cut. It deliberately excludes stylistic resemblance, which plan-doc-eval flags as favouring the original author.

Reports about existing work need no separate dimension set. They are whole-document cases whose fidelity is judged against the material they describe, and the dimensions above name their usual faults: a buried conclusion (salience), unintroduced shorthand (clarity), sentences that do not follow from each other (organization), and guesses stated as findings (risks).

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

### Reader-reported concerns

Readers who steer projects from agent-written reports without reading the code describe a second set of faults ([thread and replies, 2026-10-23](https://x.com/kitten_beloved/status/2113422896739860534)). They are placed in the same way.

| Concern | Primary dimension | Also affects | Boundary |
|---|---|---|---|
| Misplaced salience | salience_and_synthesis | concision, purpose_and_audience | Detail placed in a reference section after the main points is not misplaced. |
| Non-sequiturs | organization_and_progression | continuity | A new paragraph or section that announces a change of topic is not a non-sequitur. |
| Unintroduced terms and shorthand | clarity_and_precision | organization_and_progression, salience_and_synthesis | Terms the intended reader already uses (from the brief or the prefix) need no introduction. |
| Unmarked uncertainty | risks_and_open_questions | fidelity | Plain statements of facts the material shows directly need no evidence marker. |
| Fragmenting format | organization_and_progression | salience_and_synthesis | Lists of genuinely parallel items, steps or reference values are not fragmenting. |

Each concern has at least one concern-tagged fixture whose target is its primary dimension. Lost requirements, for example, has `coverage_lost_requirement`, and unmarked uncertainty has `risks_caveats_removed`.

## Judge templates

[templates/whole_document.md](templates/whole_document.md) shows the brief and two documents. [templates/continuation.md](templates/continuation.md) shows the prefix, the optional section request given to the generator, and two candidate next sections. [templates/whole_document_single.md](templates/whole_document_single.md) and [templates/continuation_single.md](templates/continuation_single.md) show one document or section, for cases with nothing to compare against, such as a single report. All four follow the same contract:

- **Blinded pairs.** Candidates appear only as A and B. The templates take no origin, source, URL or provenance fields, and they tell the judge that order and labels carry no information. Randomising order and running swapped pairs is the runner's job.
- **One dimension at a time, evidence first.** This follows G-Eval and Prometheus. For each dimension the judge cites passages, then gives a 1–5 score per candidate against the anchors and a per-dimension preference. The overall preference is asked for separately and is never computed from the dimension scores, so disagreements between dimensions stay visible.
- **Bias instructions.** Length is not quality (verbosity bias). Consistent elaboration is not a fidelity fault. For continuations, a candidate is not rewarded for imitating the prefix author's style.
- **Track separation.** `render_judge()` lists only the dimensions that apply to the case type. Track notes tell continuation judges to measure coverage against what the prefix promised and fidelity against what the prefix established. The two tracks use different templates and are never pooled.
- **Single-document judging.** `render_single()` takes the same inputs as `render_judge()` with one document. The judge scores each dimension against its anchors with no comparison and is told to use the whole scale, since single scores tend to bunch at 4 and 5. Whether paired preferences and single scores agree is itself a calibration question.
- **Output contract.** Paired: a JSON object with one row per dimension (`dimension`, `evidence`, `rationale`, `score_a`, `score_b`, `preference`), plus `overall_preference` and `overall_rationale`. Single: rows with `score` instead, plus `overall_score` and `overall_rationale`. `validate_judgment()` checks either (`single=True` for the second), so the runner can treat a malformed reply as a failed evaluation rather than a score.
- **Case mapping.** The case catalog's `pm_plan` cases are whole-document cases: the runner passes the instruction and the recovered conversation as the brief, with `document_kind` "PM plan", so fidelity is judged against the human turns. Brief attachments are appended to the brief text for the same reason. Reports are whole-document cases too: the brief is the request and `material` holds what the report describes (diffs, code excerpts, logs, test output), shown in its own section so that fidelity is judged against it. A case with no brief at all must say so with `no_brief=True`; the judge is then told that no brief exists rather than shown an empty one.

Render a fixture's prompt with `python3 experiments/plan-writing/rubric.py --render whole_document`, `--render continuation` or `--render <fixture id>`, and add `--single strong` or `--single weak` for the single-document prompt; `--write-doc` regenerates the dimension reference below.

## What calibration must establish

The runner and calibration PR decides which of these measures are usable. For each dimension and case type it needs to report:

- Consistency across repeated judgments and across swapped order (position bias, MT-Bench).
- Agreement between frontier and JEV judges, and with automatic candidates where they exist.
- Sensitivity to length (the `length_ratio` covariate, length-controlled AlpacaEval), to formatting (the `format_density` covariate, format bias), to source identity and, for continuations, to style match (the `style_distance` covariate).
- Agreement between paired preferences and single-document scores on the same documents, so each mode is used only where it is reliable.
- Whether the fixtures come out in the expected direction on their target dimension without moving the other dimensions as much. Dimensions listed in a fixture's `also_moves` are allowed to move and are left out of that comparison; read a judge that moves them as consistent with the source's framing, not as confusing dimensions. This is the check that dimensions stay distinct. A judge that scores every dimension from one overall impression will fail it. Huang et al. find that fine-tuned judges generalise poorly beyond the evaluation scheme they were trained on, so this has to be checked for each judge.

Measures marked `deferred` need inference-engine access (classifier or NLI probabilities). Plan-doc-eval places them outside the first PRs.

## Fixtures

Each file in [fixtures/](fixtures/) holds a `strong` and a `weak` text, the target `dimension`, any `concerns` it exercises, `held_constant` (what the pair keeps equal), `notes` (what the weak text breaks and what else differs) and, where one exists, the brief, prefix or material. Every text is quoted from a published source, recorded per part in `provenance` (a reference id and a locator), and nothing in a fixture was written for the rubric. The pairs come in four kinds (`pair_kind`):

- **before_after**: a published rewrite whose author presents one version as the better one (SEC handbook, Google Technical Writing, Federal Plain Language Guidelines, UNC, DA PAM 600-67, Berry et al.).
- **erratum**: a verified IETF erratum, the published text against its correction.
- **revision_history**: two revisions of a real document, usually with a reviewer comment naming the fault (PEPs, Rust RFCs, KEPs, Internet-Drafts, Go release notes).
- **annotated_dataset**: two summaries of one article with human faithfulness labels (XSum).

Two things in a fixture have different standing, and the files keep them apart:

- **Which text is better** is never our call. `direction_source` records who made it: an independent verifier (a verified erratum), annotators, an oversight body, a maintainer's fix, a reviewer whose comment the next revision answers, the source's author presenting a rewrite, or, weakest, only the author's own label. In revision pairs "strong" means the revision that answered the comment; nobody necessarily re-reviewed it.
- **Which dimension the pair tests** is our reading. Sources say "this is better" in their own terms, which do not always match a rubric dimension: Berry et al. call the "up to 12" pair ambiguity, filed here under verifiability; the SEC calls its pair abstraction, filed here under clarity. So `source_framing` quotes the source's own words for the fault, with its reference and locator, and `also_moves` lists the other dimensions the pair can legitimately move (because of confounds or because the source's framing points there). `dimension` stays the target.

Two fixtures join two verbatim passages of one document with `[...]` so that a contradiction between sections fits in one case; their notes say so.

Published pairs cannot be held to one difference. Each fixture's notes say what else changes, and pairs whose lengths differ by more than 1.6 times carry `length_confound` so calibration can keep them apart from verbosity bias. The padding pairs are long on the weak side by design and double as a verbosity-bias probe: a judge that prefers the padded text is rewarding length. Some sources give no brief; those whole-document fixtures render with `no_brief`. `fidelity_report_nonexistent_api` is a report judged against material: release notes that named a function the shipped code does not define, with the code's exported declarations as the material.

## Limitations

The dimensions come from published guidance and are not yet validated against preferences on this corpus. Some, such as rationale and risks, matter more for design proposals than for reference documentation, and calibration may show they should be weighted or reported per document kind. The automatic candidates are specified here but not implemented. The published examples come from many domains (finance, the military, intelligence, protocols, programming languages) because that is where reviewed before/after pairs exist; few are planning documents or code reports, and none is a PM plan, so calibration should check that fixture results carry over to the corpus. ISO, IEEE and INCOSE texts are cited from their published descriptions and public summaries, not from purchased full texts.

## Dimension reference

<!-- GENERATED: python3 experiments/plan-writing/rubric.py --write-doc -->
| Dimension | Case types | Readiness | Automatic candidates | Concerns |
|---|---|---|---|---|
| purpose_and_audience | whole_document, continuation | calibration_required | — | padding, misplaced_salience |
| salience_and_synthesis | whole_document, continuation | automatic_candidate | lead_coverage | misplaced_salience, unintroduced_terms, fragmenting_format |
| fidelity | whole_document, continuation | automatic_candidate | cited_artifact_resolution | fidelity, lost_requirements, unmarked_uncertainty |
| requirement_coverage | whole_document, continuation | automatic_candidate | brief_item_lexical_recall, pm_plan_field_preservation | lost_requirements, fidelity |
| scope_and_abstraction | whole_document, continuation | automatic_candidate | implementation_token_density | premature_implementation_detail |
| rationale_and_alternatives | whole_document, continuation | calibration_required | — | premature_implementation_detail |
| organization_and_progression | whole_document, continuation | automatic_candidate | define_before_use, adjacent_section_overlap, adjacent_sentence_link, list_fragmentation, format_density (bias covariate) | poor_progression, padding, non_sequiturs, fragmenting_format, unintroduced_terms |
| concision | whole_document, continuation | automatic_candidate | redundancy_rate, filler_lexicon_rate, length_ratio (bias covariate) | padding, premature_implementation_detail, misplaced_salience |
| clarity_and_precision | whole_document, continuation | automatic_candidate | vague_term_rate, undefined_acronyms, unglossed_identifiers | unintroduced_terms |
| internal_consistency | whole_document, continuation | automatic_candidate | term_variant_detection, pm_dependency_agreement | fidelity |
| risks_and_open_questions | whole_document, continuation | automatic_candidate | evidence_pointer_rate | unmarked_uncertainty |
| verifiability | whole_document, continuation | automatic_candidate | pm_tests_field_present | lost_requirements |
| genre_conventions | whole_document, continuation | automatic_candidate | template_section_presence, pm_plan_parse | — |
| continuity | continuation | automatic_candidate | prefix_repetition, established_term_reuse, style_distance (bias covariate) | poor_progression, padding, non_sequiturs |

### purpose_and_audience — Purpose, context and audience

**Definition.** The document states what problem it addresses, why now, for whom, and what decision or action it asks of the reader, and its content is selected for that reader's needs.

**Continuation.** The section serves the purpose the prefix has established and the role the section's position implies; re-introducing the document's purpose is scored under continuity, not here.

**Derived from.** AAC&U 'context of and purpose for writing'; ISO 24495 'relevant'; PEP motivation, KEP motivation/goals, Shape Up problem and appetite, Google 'context and scope'; Grice's maxim of relation.

**Sources.** [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication); [ISO 24495-1:2023 Plain language — Part 1: Governing principles and guidelines](https://www.iso.org/standard/78907.html); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [Shape Up, Chapter 6: Write the Pitch (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.5-chapter-06); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/); [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003)

**Detection guidance.**

- Can a reader state the problem, the intended reader and the requested decision after the first screen?
- Is there material that serves no identifiable reader need (history of the author's process, general tutorials, marketing)?
- Does the document address a different problem than the brief asks for, or a generic version of it?
- For reports about existing work (digests, sign-off and QA reports), can the reader tell what the report asks of them: a decision, an approval, something to watch? Whether the details carry weight in proportion to that is scored under salience_and_synthesis.

**Not a fault.**

- A short motivation when the brief already establishes shared context.
- Background that a reviewer needs to evaluate the decision.

**Example, stronger** ([U.S. Securities and Exchange Commission. A Plain English Handbook: How to create clear SEC disclosure documents](https://www.sec.gov/pdf/handbook.pdf), Chapter 6, 'Try personal pronouns', printed p. 22). The rewrite names the reader and the decision the summary serves ('before you decide how to vote').

> Because this is a summary, it does not contain all the information that may be important to you. You should read the entire proxy statement and its appendices carefully before you decide how to vote.

**Example, weaker** ([U.S. Securities and Exchange Commission. A Plain English Handbook: How to create clear SEC disclosure documents](https://www.sec.gov/pdf/handbook.pdf), Chapter 6, 'Try personal pronouns', printed p. 22)

> This Summary does not purport to be complete and is qualified in its entirety by the more detailed information contained in the Proxy Statement and the Appendices hereto, all of which should be carefully reviewed.

**Score anchors.** 1: Purpose absent or wrong; content generic or aimed at no identifiable reader. 3: Purpose recoverable but late or vague; some content serves no reader need. 5: Problem, reader and requested decision clear early; content consistently selected for that reader.

**Candidate measures** (readiness: calibration_required).

- `judge_purpose` (judge, needs_calibration): Rubric judge score and paired preference on this dimension.

**Fixtures.** `fixtures/purpose_irrelevant_intro.json`. May also move: `clarity_terms_of_art`, `progression_opening_sentence`, `salience_buried_warning`

### salience_and_synthesis — Salience and synthesis

**Definition.** Emphasis follows importance: what the reader most needs (the main conclusion, the decisions, the core constraints) comes early and gets the most weight, details are subordinated to the points they support, and the document pulls them together into an overview the reader can act on rather than an inventory of facts.

**Continuation.** Within the section: its main point is clear and its details serve it. Repeating the prefix is scored under continuity, not here.

**Derived from.** SummEval 'relevance' (selection of the important content of a source); Minto's governing thought and pyramid; the Army's bottom line up front (DA PAM 600-67); GOV.UK front-loading; plain-language 'put the main point first'; Grice's maxims of quantity and relation.

**Sources.** [Fabbri, A. R. et al. SummEval: Re-evaluating Summarization Evaluation. TACL 9](https://arxiv.org/abs/2007.12626); [Minto, B. The Pyramid Principle: Logic in Writing and Thinking (3rd ed.). Pearson](https://www.barbaraminto.com/); [Headquarters, Department of the Army. DA Pamphlet 600-67, Effective Writing for Army Leaders](https://armywriter.com/DAP600-67.pdf); [GOV.UK content design: writing for GOV.UK](https://www.gov.uk/guidance/content-design/writing-for-gov-uk); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003)

**Detection guidance.**

- After the first screen, can the reader state the main conclusion and what needs their decision?
- Compare space with importance: flag details that get more words than the core constraints or decisions, and core constraints mentioned once in passing.
- Flag details introduced without saying what they mean for the reader (why this matters here).
- Flag inventories: lists of facts, components or changes with no statement of what they add up to.
- Filler and restatement are scored under concision and the order of sections under organization_and_progression; this dimension is about what gets weight and whether the parts are synthesised.

**Not a fault.**

- Reference sections or appendices that hold detail on purpose, after the main points.
- Genre-mandated order that puts background first, when the main point is still stated where readers of that genre look (abstract, summary, executive summary).

**Example, stronger** ([IETF draft-ietf-tsvwg-tinymt32 revisions -03 and -04 (published as RFC 8682)](https://www.ietf.org/archive/id/draft-ietf-tsvwg-tinymt32-04.txt), Abstract, revision -03 (weaker) and -04 (stronger)). An IESG reviewer said the not-for-cryptography warning was 'more buried than it should be'; the next revision put it in the abstract.

> Abstract
>
> This document describes the TinyMT32 Pseudo Random Number Generator (PRNG) that produces 32-bit pseudo-random unsigned integers and aims at having a simple-to-use and deterministic solution.  This PRNG is a small-sized variant of Mersenne Twister (MT) PRNG.  The main advantage of TinyMT32 over MT is the use of a small internal state, compatible with most target platforms that include embedded devices, while keeping a reasonably good randomness that represents a sigificant improvement compared to the Park-Miller Linear Congruential PRNG.  However, neither the TinyMT nor MT PRNG are meant to be used for cryptographic applications.

**Example, weaker** ([IETF draft-ietf-tsvwg-tinymt32 revisions -03 and -04 (published as RFC 8682)](https://www.ietf.org/archive/id/draft-ietf-tsvwg-tinymt32-04.txt), Abstract, revision -03 (weaker) and -04 (stronger))

> Abstract
>
> This document describes the TinyMT32 Pseudo Random Number Generator (PRNG) that produces 32-bit pseudo-random unsigned integers and aims at having a simple-to-use and deterministic solution.  This PRNG is a small-sized variant of Mersenne Twister (MT) PRNG [MT98].  The main advantage of TinyMT32 over MT is the use of a small internal state, compatible with most target platforms including embedded devices, while keeping a reasonably good randomness.

**Score anchors.** 1: Main point and core constraints buried or missing; an inventory of details with no synthesis. 3: Main point findable; some core constraints underweighted or details left unconnected to what they mean. 5: Main point and decisions up front; weight tracks importance; details serve a clear overview.

**Candidate measures** (readiness: automatic_candidate).

- `judge_salience` (judge, needs_calibration): Rubric judge; must name the points it considers most important and where the document places them.
- `lead_coverage` (deterministic, automatic_candidate): Content-word recall of the brief's obligation items (for reports, of headline facts in the material such as failing tests or changed interfaces) within the first fifth of the document, compared with the reference distribution for the document kind; flags buried core constraints.
- `emphasis_allocation` (model_assisted, needs_calibration): A prompted model ranks the brief's or material's items by importance; words spent on each item in the document are compared with that ranking.

**Fixtures.** `fixtures/salience_buried_warning.json`, `fixtures/salience_report_finding_last.json`. May also move: `progression_opening_sentence`, `purpose_irrelevant_intro`

### fidelity — Fidelity to brief, prefix or described material

**Definition.** Every claim, decision and constraint the document attributes to the brief (or, for continuations, to the prefix) is supported by it and none contradicts it; elaboration beyond the input is consistent with it and recognisable as the writer's proposal rather than presented as agreed fact. For reports about existing work, every claim about the material the report describes (code, diffs, logs, test results) is supported by that material.

**Continuation.** Judge against the prefix: no contradiction of decisions, names, numbers or scope established earlier in the document.

**Derived from.** ISO 29148 'correct'; summarisation consistency literature (FActScore atomic claims, SummaC/FactCC entailment, QAGS question answering, SummEval 'consistency'); Grice's maxim of quality.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [Min, S. et al. FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation](https://arxiv.org/abs/2305.14251); [Laban, P. et al. SummaC: Re-Visiting NLI-based Models for Inconsistency Detection in Summarization. TACL 10](https://arxiv.org/abs/2111.09525); [Kryściński, W. et al. Evaluating the Factual Consistency of Abstractive Text Summarization. EMNLP](https://arxiv.org/abs/1910.12840); [Wang, A., Cho, K. and Lewis, M. Asking and Answering Questions to Evaluate the Factual Consistency of Summaries. ACL](https://arxiv.org/abs/2004.04228); [Fabbri, A. R. et al. SummEval: Re-evaluating Summarization Evaluation. TACL 9](https://arxiv.org/abs/2007.12626); [Grice, H. P. Logic and Conversation. In Cole and Morgan (eds.), Syntax and Semantics 3: Speech Acts, 41–58](https://doi.org/10.1163/9789004368811_003)

**Detection guidance.**

- Split the document into atomic claims; for each claim that refers to the input, check that the input supports it.
- Flag numbers, names, identifiers, dates and owners that do not appear in the input and are stated as given rather than proposed.
- Flag reversals: a constraint from the input stated with the opposite polarity or a weakened obligation (MUST to SHOULD).
- For PM plans, flag decisions attributed to the human that the conversation shows the assistant proposed and the human did not accept.
- For reports, check claims about code, tests and runs against the material: a file, function, test or result the report names must exist and do or say what the report says.

**Not a fault.**

- Useful elaboration, reasoning or design detail that is consistent with the input, even when the input never mentions it.
- Explicitly marked proposals or assumptions.

**Example, stronger** ([RFC 5134, verified erratum 1325: lexical-equivalence rule restated with the wrong scope from RFC 2141](https://www.rfc-editor.org/errata/eid1325), RFC 5134 Section 2 as published (weaker) and as corrected (stronger)). The source rule (RFC 2141) compares 'urn:' and the namespace id case-insensitively; the published text claimed the entire URN is case-sensitive.

> Rules for Lexical Equivalence:
>
>          The namespace-specific part of the URN is case-sensitive.

**Example, weaker** ([RFC 5134, verified erratum 1325: lexical-equivalence rule restated with the wrong scope from RFC 2141](https://www.rfc-editor.org/errata/eid1325), RFC 5134 Section 2 as published (weaker) and as corrected (stronger))

> Rules for Lexical Equivalence:
>
>          The entire URN is case-sensitive.

**Score anchors.** 1: Contradicts the input on a material point or invents agreed decisions. 3: No material contradiction, but some unsupported specifics are stated as given. 5: All input-attributed content supported; elaboration consistent and clearly the writer's proposal.

**Candidate measures** (readiness: automatic_candidate).

- `judge_fidelity` (judge, needs_calibration): Rubric judge with the brief or prefix in view; must quote the conflicting passages.
- `atomic_claim_support` (model_assisted, needs_calibration): FActScore-style: a prompted model decomposes the draft into input-referring claims and labels each supported/contradicted/unsupported against the input.
- `nli_consistency` (model_assisted, deferred): SummaC-style sentence-pair entailment between input and draft using an NLI classifier's probabilities.
- `cited_artifact_resolution` (deterministic, automatic_candidate): For reports, file paths, symbols, commit ids and test names the report cites resolve in the repository at the stated revision, and quoted counts or log lines appear in the material. Catches invented references, not wrong descriptions of real ones.

**Fixtures.** `fixtures/fidelity_report_nonexistent_api.json`, `fixtures/fidelity_rule_scope.json`, `fixtures/fidelity_summary_contradiction.json`, `fixtures/fidelity_summary_table_contradicts_prefix.json`

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

**Example, stronger** ([RFC 4918 (WebDAV), verified erratum 1430: MKCOL support requirement dropped from RFC 2518](https://www.rfc-editor.org/errata/eid1430), RFC 4918 Section 9.3 as published (weaker) and as corrected (stronger)). The predecessor (RFC 2518 Section 8.3) required every DAV-compliant resource to support MKCOL; the revision dropped that requirement.

> 9.3 MKCOL Method
>
>    The MKCOL method is used to create a new collection. All DAV compliant
>    resources MUST support the MKCOL method.
>
>    MKCOL creates a new collection resource at the location specified by
>    the Request-URI. [...]

**Example, weaker** ([RFC 4918 (WebDAV), verified erratum 1430: MKCOL support requirement dropped from RFC 2518](https://www.rfc-editor.org/errata/eid1430), RFC 4918 Section 9.3 as published (weaker) and as corrected (stronger))

> 9.3.  MKCOL Method
>
>    MKCOL creates a new collection resource at the location specified by
>    the Request-URI. [...]

**Score anchors.** 1: Several explicit requirements missing or diluted beyond recognition. 3: Most present; one material requirement missing, diluted or misplaced. 5: Every requirement traceable to an appropriate place in the document.

**Candidate measures** (readiness: automatic_candidate).

- `judge_coverage` (judge, needs_calibration): Rubric judge lists brief items and marks each covered/diluted/missing.
- `brief_item_lexical_recall` (deterministic, automatic_candidate): Split the brief into items (list entries, sentences with obligation words); for each item compute content-word recall in the best-matching document paragraph; report items under a threshold. Paraphrase defeats it, so it flags rather than scores.
- `pm_plan_field_preservation` (deterministic, automatic_candidate): For PM plan cases, parse PR blocks with pm_core.plans.parser.parse_plan_prs and check that titles and depends_on named in the conversation's accepted structure survive.
- `brief_question_answering` (model_assisted, needs_calibration): QAGS-style: generate questions from the brief, answer them from the draft only, compare with answers from the brief.

**Fixtures.** `fixtures/coverage_lost_requirement.json`. May also move: `fidelity_summary_contradiction`

### scope_and_abstraction — Scope and level of abstraction

**Definition.** The document works at the level of detail its kind and stage call for: it fixes the decisions a reader must review now, states goals and non-goals, and leaves implementation choices that do not affect those decisions to the people who implement them.

**Continuation.** The section's level of detail matches the prefix's and the section's role; a reference-level section may be detailed where an overview section may not.

**Derived from.** ISO 29148 and INCOSE 'appropriate' level and solution-free requirements; NASA implementation-free requirements; Google design docs ('really implementation manuals'); Shape Up 'rough, solved, bounded' (wireframes too concrete, words too abstract; no-gos as the boundary); RFC 4101 detail for implementors gets in the way of review; KEP goals/non-goals; Diátaxis separation of purposes.

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
- In reports about existing work, file, function, test or commit references given as evidence for a claim: they locate, they do not prescribe.

**Example, stronger** ([python/peps pull request 2997: PEP 705 TypedMapping review](https://github.com/python/peps/pull/2997), PEP 705 Backwards Compatibility, reviewed draft (weaker) and next revision (stronger)). The reviewer called the metaclass workaround 'a bit too much implementation detail' and asked to cut everything from 'Users wanting to inherit'.

> Backwards Compatibility
> =======================
>
> This PEP changes the rules for how ``TypedDict`` behaves (allowing subclasses to
> inherit from ``TypedMapping`` protocols in a way that changes the resulting
> overloads), so code that inspects ``TypedDict`` types will have to change. This
> is expected to mainly affect type-checkers.
>
> The ``TypedMapping`` type will be added to the ``typing_extensions`` module,
> enabling its use in older versions of Python.

**Example, weaker** ([python/peps pull request 2997: PEP 705 TypedMapping review](https://github.com/python/peps/pull/2997), PEP 705 Backwards Compatibility, reviewed draft (weaker) and next revision (stronger))

> Backwards Compatibility
> =======================
>
> This PEP changes the rules for how ``TypedDict`` behaves (allowing subclasses to
> inherit from ``TypedMapping`` protocols in a way that changes the resulting
> overloads), so code that inspects ``TypedDict`` types will have to change. This
> is expected to mainly affect type-checkers.
>
> The ``TypedMapping`` type will be added to the ``typing_extensions`` module,
> enabling its use in older versions of Python. Users wanting to inherit from
> both ``TypedDict`` and ``TypedMapping`` will need to use
> ``typing_extensions.TypedDict`` in these versions, as the existing ``typing`` implementation
> of ``TypedDict`` does an ``is`` check on the metaclass of all base classes and raises
> an error if any other metaclass is found. This would cause any subclass of both
> that implementation and a ``TypedMapping`` protocol to trigger an error at runtime.

**Score anchors.** 1: Mostly implementation steps or so abstract that nothing is decided. 3: Right level overall with notable stretches of unmotivated implementation detail or vagueness. 5: Detail tracks the decisions; boundaries and non-goals explicit.

**Candidate measures** (readiness: automatic_candidate).

- `judge_abstraction` (judge, needs_calibration): Rubric judge; must cite the passages it considers premature.
- `implementation_token_density` (deterministic, automatic_candidate): Share of tokens inside code spans/blocks plus identifiers, file paths, line numbers and signatures per 1000 words, compared with the reference distribution for the same document kind.

**Fixtures.** `fixtures/scope_spec_impl_detail.json`

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

**Example, stronger** ([rust-lang/rfcs pull request 2539: cfg_attr expanding to multiple attributes](https://github.com/rust-lang/rfcs/pull/2539), Rationale and alternatives, before and after commit ad8ba5ef). The draft said 'There are no other alternatives'; after a reviewer raised the bracket syntax, the author added it with a reason for rejecting it.

> # Rationale and alternatives [rationale-and-alternatives]: #rationale-and-alternatives
>
> We could require that multiple attributes must be within in a delimiter to make it so that it's always two arguments at the top level. E.g., `#[cfg_attr(predicate, [attr, attr])]`. While this could increase clarity, it mostly seems like it would just add noise. In the multiline case, it already reads pretty clear with the predicate on the first line and each attribute indented.
>
> The default alternative of not doing this is a possibility. It would just mean that conditionally including attributes is slightly less ergonomic than it could be.

**Example, weaker** ([rust-lang/rfcs pull request 2539: cfg_attr expanding to multiple attributes](https://github.com/rust-lang/rfcs/pull/2539), Rationale and alternatives, before and after commit ad8ba5ef)

> # Rationale and alternatives [rationale-and-alternatives]: #rationale-and-alternatives
>
> There are no other alternatives.
>
> By not doing this, conditionally including attributes is slightly less ergonomic than it can be.

**Score anchors.** 1: Decisions asserted without reasons. 3: Reasons for main decisions; trade-offs or alternatives thin or straw-man. 5: Each consequential decision has specific reasons, accepted costs and credible alternatives.

**Candidate measures** (readiness: calibration_required).

- `judge_rationale` (judge, needs_calibration): Rubric judge score and paired preference.

**Fixtures.** `fixtures/rationale_no_alternatives.json`. May also move: `risks_caveats_removed`

### organization_and_progression — Organization and progression

**Definition.** The document moves from context to decision to detail in an order a reader can follow: overview before specifics, terms defined before use, dependencies before what depends on them, and each part building on what came before, down to each sentence picking up from the one before it, without formatting that cuts the links between connected ideas.

**Continuation.** Judge order within the section; restarting the prefix, looping back over it or jumping ahead of material it has not yet introduced is scored under continuity, not here.

**Derived from.** Gopen and Swan reader expectations (old before new, stress position); Williams on cohesion and coherence; Minto governing idea first; RFC 4101 model before detail; Rust RFC guide-level before reference-level; 6+1 'organization'; AAC&U 'content development'; plain-language 'organize to meet readers' needs'; GOV.UK front-loading; Coh-Metrix cohesion and the entity-grid model of local coherence; format-bias findings for the judge-side risk of rewarding lists and bold.

**Sources.** [Gopen, G. D. and Swan, J. A. The Science of Scientific Writing. American Scientist 78(6):550–558](https://www.americanscientist.org/blog/the-long-view/the-science-of-scientific-writing); [Williams, J. M. and Bizup, J. Style: Lessons in Clarity and Grace (12th ed.). Pearson](https://www.pearson.com/en-us/subject-catalog/p/style-lessons-in-clarity-and-grace/P200000003473); [Minto, B. The Pyramid Principle: Logic in Writing and Thinking (3rd ed.). Pearson](https://www.barbaraminto.com/); [RFC 4101 — Writing Protocol Models (E. Rescorla)](https://www.rfc-editor.org/rfc/rfc4101); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [6+1 Trait Writing model (Education Northwest)](https://educationnorthwest.org/traits); [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication); [Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/); [GOV.UK content design: writing for GOV.UK](https://www.gov.uk/guidance/content-design/writing-for-gov-uk); [Graesser, A. C., McNamara, D. S., Louwerse, M. M. and Cai, Z. Coh-Metrix: Analysis of text on cohesion and language. Behavior Research Methods 36:193–202](https://doi.org/10.3758/BF03195564); [Barzilay, R. and Lapata, M. Modeling Local Coherence: An Entity-Based Approach. Computational Linguistics 34(1):1–34](https://aclanthology.org/J08-1001/); [Zhang, X. et al. From Lists to Emojis: How Format Bias Affects Model Alignment](https://arxiv.org/abs/2409.11704)

**Detection guidance.**

- Read only headings and first sentences: do they tell the argument in order?
- Flag terms, components or PRs used before they are introduced, and conclusions that appear before the material supporting them without signposting.
- Flag sections whose order would have to change for the dependencies among them to make sense (for PM plans, a PR described before the PRs it depends on without reason).
- Flag repeated returns to the same topic in separate places.
- Within paragraphs, check that each sentence picks up something from the one before (known information first, new information last). Flag non-sequiturs: sentences whose link to the previous one is a leap the reader has to supply.
- Flag formatting that fragments reasoning: bullet lists whose items depend on each other but drop the connectives (because, so, but, which means) that would say how, and headings or bold so dense they flatten what matters.

**Not a fault.**

- A summary-first structure that states conclusions up front by design (pyramid order).
- Genre-mandated section order.
- Lists of genuinely parallel items, steps or reference values.

**Example, stronger** ([The Writing Center, University of North Carolina at Chapel Hill. Flow](https://writingcenter.unc.edu/tips-and-tools/flow/), Cohesion, known-to-new sequencing, versions 1 and 2). The source says both versions contain the same information; in the stronger one each sentence opens on what the previous one ended with.

> The compact fluorescent bulb has become the standard bulb for household lamps. Until recently, most lamps used incandescent bulbs. This type of bulb operates by heating a tungsten filament until it glows, throwing off light. Unfortunately, heating the filament wastes approximately 90% of the energy used to produce the light.

**Example, weaker** ([The Writing Center, University of North Carolina at Chapel Hill. Flow](https://writingcenter.unc.edu/tips-and-tools/flow/), Cohesion, known-to-new sequencing, versions 1 and 2)

> The compact fluorescent bulb has become the standard bulb for household lamps. Until recently, most people used incandescent bulbs in their lamps. Heating a tungsten filament until it glows, throwing off light, is how this type of bulb operates. Unfortunately, approximately 90% of the energy used to produce the light is wasted by heating the filament.

**Score anchors.** 1: Order obstructs understanding; frequent use-before-introduction, loops, non-sequiturs or fragments that leave the reader to supply the connections. 3: Generally ordered with some jumps, forward references, repeated returns or unconnected sentences. 5: Clear progression at every level; headings alone tell the argument and sentences follow from one another.

**Candidate measures** (readiness: automatic_candidate).

- `judge_progression` (judge, needs_calibration): Rubric judge score and paired preference.
- `define_before_use` (deterministic, automatic_candidate): Acronyms and capitalised/coded terms whose first occurrence is not a definition pattern (expansion, 'X is', 'we call') but whose defining occurrence appears later.
- `adjacent_section_overlap` (deterministic, automatic_candidate): Coh-Metrix-style content-word overlap between adjacent sections versus non-adjacent ones; low adjacency relative to the reference flags jumps.
- `adjacent_sentence_link` (deterministic, automatic_candidate): Share of sentences that share no content word or entity with either of the two sentences before them (Coh-Metrix referential cohesion, entity-grid transitions), compared with the reference distribution; flags non-sequiturs.
- `list_fragmentation` (deterministic, automatic_candidate): Share of words in list items, and share of list items with no clause connective, compared with the reference distribution for the document kind.
- `format_density` (deterministic, automatic_candidate, bias covariate): Headings, list items and bold spans per 1000 words; recorded to measure how much judges reward formatting, never scored as quality.

**Fixtures.** `fixtures/progression_known_to_new.json`, `fixtures/progression_opening_sentence.json`, `fixtures/progression_stacked_headings.json`. May also move: `salience_report_finding_last`

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

**Example, stronger** ([Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/), III. Write clearly, 'Use short, simple words', printed p. 36). A published parody of padded prose and its one-line rewrite; the long version also carries hedges the short one drops.

> More night jobs would keep youths off the streets.

**Example, weaker** ([Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/), III. Write clearly, 'Use short, simple words', printed p. 36)

> There is no escaping the fact that it is considered very important to note that a number of various available applicable studies ipso facto have generally identified the fact that additional appropriate nocturnal employment could usually keep juvenile adolescents off thoroughfares during the night hours, including but not limited to the time prior to midnight on weeknights and/or 2 a.m. on weekends.

**Score anchors.** 1: Much of the text is filler, restatement or generic advice. 3: Mostly informative with noticeable padding in places. 5: Dense with needed information; elaboration earns its place.

**Candidate measures** (readiness: automatic_candidate).

- `judge_concision` (judge, needs_calibration): Rubric judge; must point to deletable passages. Calibration must check length sensitivity (verbosity bias) explicitly.
- `redundancy_rate` (deterministic, automatic_candidate): Share of content-word 4-grams that repeat across paragraphs, after removing headings and quoted input.
- `filler_lexicon_rate` (deterministic, automatic_candidate): Vale-style lexicon of filler and throat-clearing phrases ('it is important to note', 'as mentioned above', 'in other words') per 1000 words.
- `length_ratio` (deterministic, automatic_candidate, bias covariate): Draft length over reference length; recorded to measure judge length sensitivity, never scored as quality.

**Fixtures.** `fixtures/concision_padding.json`. May also move: `purpose_irrelevant_intro`, `salience_report_finding_last`, `scope_spec_impl_detail`

### clarity_and_precision — Clarity and precision

**Definition.** Statements have one reasonable reading: obligations are explicit, quantities and conditions are specific, terms are defined, and sentences are readable for the intended audience.

**Continuation.** Terms the section introduces are defined; renaming or redefining terms the prefix established is scored under continuity, not here.

**Derived from.** ISO 29148 'unambiguous'; INCOSE rules against vague terms, escape clauses and open-ended lists; RFC 8174 requirement keywords; RFC 7322 editorial clarity; Google style; ISO 24495 'understandable'; 6+1 'word choice' and 'conventions'; AAC&U 'control of syntax and mechanics'.

**Sources.** [ISO/IEC/IEEE 29148:2018 Systems and software engineering — Life cycle processes — Requirements engineering](https://www.iso.org/standard/72089.html); [INCOSE Guide to Writing Requirements (GtWR), version 4](https://www.incose.org/docs/default-source/working-groups/requirements-wg/gtwr/incose_rwg_gtwr_v4_040423_final_drafts.pdf); [RFC 8174 — Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words](https://www.rfc-editor.org/rfc/rfc8174); [RFC 7322 — RFC Style Guide](https://www.rfc-editor.org/rfc/rfc7322); [Google developer documentation style guide](https://developers.google.com/style); [ISO 24495-1:2023 Plain language — Part 1: Governing principles and guidelines](https://www.iso.org/standard/78907.html); [6+1 Trait Writing model (Education Northwest)](https://educationnorthwest.org/traits); [AAC&U VALUE Rubric: Written Communication](https://www.aacu.org/initiatives/value-initiative/value-rubrics/value-rubrics-written-communication)

**Detection guidance.**

- Flag vague qualifiers (appropriate, as needed, fast, robust, user-friendly, etc., and/or) where a reviewer needs a specific value or condition.
- Flag obligations whose force is unclear (should vs must) when it matters.
- Flag pronouns or 'this' with more than one plausible referent, and undefined acronyms. One concept named several ways is scored under internal_consistency, not here.
- Flag shorthand from the writer's working context (internal names, ticket or PR ids, code identifiers, jargon) used as if the reader shared that context. A report for a reader who does not read the code needs each such term introduced or described in plain words.

**Not a fault.**

- Deliberate openness that is labelled as an open question.

**Example, stronger** ([Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/), II. Organize, 'Address one person, not a group', printed p. 10). 'Appropriate offices' and 'in a timely manner' become a 30-day deadline and a named office for each kind of applicant.

> You must apply at least 30 days before you need the certification. a. If you are an individual, apply at the State office in the State where you reside. b. If you are an organization, apply at the State office in the State where your headquarters is located.

**Example, weaker** ([Federal Plain Language Guidelines (PLAIN, plainlanguage.gov)](https://www.plainlanguage.gov/guidelines/), II. Organize, 'Address one person, not a group', printed p. 10)

> Individuals and organizations wishing to apply must file applications with the appropriate offices in a timely manner.

**Score anchors.** 1: Key statements ambiguous; obligations and conditions vague. 3: Mostly clear; some vague qualifiers or unclear obligations on material points. 5: Precise throughout where precision matters.

**Candidate measures** (readiness: automatic_candidate).

- `judge_clarity` (judge, needs_calibration): Rubric judge score and paired preference.
- `vague_term_rate` (deterministic, automatic_candidate): INCOSE-derived lexicon of vague and escape-clause terms per 1000 words.
- `undefined_acronyms` (deterministic, automatic_candidate): Acronyms never expanded in the document or input.
- `unglossed_identifiers` (deterministic, automatic_candidate): Code identifiers, paths and ids (snake_case, CamelCase, dotted or slashed tokens, PR/issue ids) whose first occurrence has no accompanying plain description in the same sentence, per 1000 words; read against the document kind, since specs legitimately name identifiers.

**Fixtures.** `fixtures/clarity_terms_of_art.json`, `fixtures/clarity_vague_quantity.json`. May also move: `concision_padding`, `fidelity_summary_contradiction`, `progression_stacked_headings`, `verifiability_boundary`, `verifiability_rollback_metrics`

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

**Example, stronger** ([RFC 5792 (PA-TNC), verified erratum 3935: 'one or more' vs 'zero or more' attributes](https://www.rfc-editor.org/errata/eid3935), RFC 5792 Section 3.1 as published (weaker) and as corrected (stronger)). Section 4 of the same RFC says a message carries 'zero or more' attributes; the published Section 3.1 said 'one or more'.

> Each PA-TNC message may
> contain zero or more attributes associated with the functional
> component identified in the component type (PA Subtype) of the
> Posture Broker (PB) protocol.

**Example, weaker** ([RFC 5792 (PA-TNC), verified erratum 3935: 'one or more' vs 'zero or more' attributes](https://www.rfc-editor.org/errata/eid3935), RFC 5792 Section 3.1 as published (weaker) and as corrected (stronger))

> Each PA-TNC message may
> contain one or more attributes associated with the functional
> component identified in the component type (PA Subtype) of the
> Posture Broker (PB) protocol.

**Score anchors.** 1: Material contradictions between sections. 3: Minor inconsistencies in naming or secondary values. 5: Fully consistent.

**Candidate measures** (readiness: automatic_candidate).

- `judge_consistency` (judge, needs_calibration): Rubric judge; must quote both sides of each contradiction.
- `term_variant_detection` (deterministic, automatic_candidate): Near-duplicate identifiers and terms (case, hyphenation, pluralisation, edit distance) used for what may be one concept.
- `pm_dependency_agreement` (deterministic, automatic_candidate): For PM plans, depends_on entries resolve to PR titles in the same plan (pm_core.plans.parser.parse_plan_prs).

**Fixtures.** `fixtures/consistency_count_contradiction.json`. May also move: `salience_report_finding_last`

### risks_and_open_questions — Risks, uncertainty and open questions

**Definition.** The document states what could go wrong, what is unknown, and which questions remain for reviewers, instead of presenting an uncertain plan as settled. Claims carry the confidence their evidence supports, and reports about existing work say what was verified and what is inferred or assumed.

**Continuation.** Applies when the section's role includes risks or unresolved questions, or when it makes claims whose uncertainty the prefix has flagged.

**Derived from.** KEP risks and mitigations; Rust unresolved questions; PEP open issues and security implications; Shape Up rabbit holes; RFC 3552 security considerations; Oxide RFD discussion states; Google cross-cutting concerns; ICD 203 analytic standards (express uncertainty, separate information from assumptions and judgments); Kent's words of estimative probability and the IPCC uncertainty guidance for calibrated language.

**Sources.** [Kubernetes KEP template (kubernetes/enhancements NNNN-kep-template)](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md); [Rust RFC template (rust-lang/rfcs 0000-template.md)](https://github.com/rust-lang/rfcs/blob/master/0000-template.md); [PEP 1 — PEP Purpose and Guidelines](https://peps.python.org/pep-0001/); [Shape Up, Chapter 6: Write the Pitch (R. Singer, Basecamp)](https://basecamp.com/shapeup/1.5-chapter-06); [RFC 3552 — Guidelines for Writing RFC Text on Security Considerations](https://www.rfc-editor.org/rfc/rfc3552); [Oxide RFD 1 — Requests for Discussion](https://rfd.shared.oxide.computer/rfd/0001); [Design Docs at Google (M. Ubl, industrialempathy.com)](https://www.industrialempathy.com/posts/design-docs-at-google/); [Intelligence Community Directive 203: Analytic Standards (ODNI)](https://www.dni.gov/files/documents/ICD/ICD-203.pdf); [Kent, S. Words of Estimative Probability. Studies in Intelligence 8(4)](https://www.cia.gov/resources/csi/static/Words-of-Estimative-Probability.pdf); [Mastrandrea, M. D. et al. Guidance Note for Lead Authors of the IPCC Fifth Assessment Report on Consistent Treatment of Uncertainties](https://www.ipcc.ch/site/assets/uploads/2017/08/AR5_Uncertainty_Guidance_Note.pdf)

**Detection guidance.**

- Look for named risks with consequences and mitigations, not a generic 'risks: bugs may occur'.
- Check that genuinely unknown things are marked as unknown. Exclusions and non-goals are scored under scope_and_abstraction, not here.
- Flag false certainty: claims about performance, adoption or compatibility without evidence or caveat.
- For reports, check that claims about the system's state or behaviour say how they are known (run, tested, read, inferred) where that is not obvious, and that inferences and untested assumptions are labelled. A report that sounds equally sure of everything fails here.
- Flag hedges that carry no information ("should be fine", "likely") where the writer could say what was checked.

**Not a fault.**

- A short or empty risks section for a small, low-risk change, if it says so.

**Example, stronger** ([rust-lang/rfcs pull request 3013: checking conditional compilation at compile time](https://github.com/rust-lang/rfcs/pull/3013), Drawbacks, before and after commit 1788dd4d). A reviewer wrote that a drawbacks section saying 'None' signals the author 'hasn't thought hard enough' about the trade-offs.

> ## Drawbacks
>
> * Adds complexity, in the form of additional command-line options.
> * As with all lints, correct code may be trigger lints. Developers will need to take time to
>   examine them and see whether they are legitimate or not.
> * To take full advantage of this, build systems (including but not limited to Cargo) must be
>   updated. However, for those systems that are not updated, there is no penalty or drawback,
>   since `--check-cfg` is opt-in.

**Example, weaker** ([rust-lang/rfcs pull request 3013: checking conditional compilation at compile time](https://github.com/rust-lang/rfcs/pull/3013), Drawbacks, before and after commit 1788dd4d)

> ## Drawbacks
>
> There are no known drawbacks to this proposal.

**Score anchors.** 1: No risks or open questions where clearly needed; false certainty, or guesses stated as findings. 3: Some specific risks; others generic or missing; confidence not always matched to evidence. 5: Specific risks with mitigations, explicit unknowns and reviewer questions; every claim as certain as its evidence and no more.

**Candidate measures** (readiness: automatic_candidate).

- `judge_risks` (judge, needs_calibration): Rubric judge score and paired preference.
- `evidence_pointer_rate` (deterministic, automatic_candidate): For reports, share of sentences that assert code or test behaviour and carry an evidence pointer (test name, command, log excerpt, path, commit) or an explicit inference marker; low rates flag unmarked guesses.

**Fixtures.** `fixtures/risks_caveats_removed.json`, `fixtures/risks_no_drawbacks.json`. May also move: `concision_padding`, `genre_missing_pep_sections`, `salience_buried_warning`, `verifiability_rollback_metrics`

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

**Example, stronger** ([Berry, D. M., Kamsties, E. and Krieger, M. M. From Contract Drafting to Software Specification: Linguistic Sources of Ambiguity — A Handbook](https://cs.uwaterloo.ca/~dberry/handbook/ambiguityHandbook.pdf), Section 5.1, examples E38 and E39, p. 20). Whether 12 aircraft get the small or the large format cannot be tested from the weaker sentence.

> For up to and including 12 aircraft, the small display format shall be used. Otherwise, the large display format shall be used.

**Example, weaker** ([Berry, D. M., Kamsties, E. and Krieger, M. M. From Contract Drafting to Software Specification: Linguistic Sources of Ambiguity — A Handbook](https://cs.uwaterloo.ca/~dberry/handbook/ambiguityHandbook.pdf), Section 5.1, examples E38 and E39, p. 20)

> For up to 12 aircraft, the small display format shall be used. Otherwise, the large display format shall be used.

**Score anchors.** 1: No checkable criteria. 3: Some concrete tests; key requirements lack checks. 5: Every material requirement has a concrete check, including failure cases.

**Candidate measures** (readiness: automatic_candidate).

- `judge_verifiability` (judge, needs_calibration): Rubric judge score and paired preference.
- `pm_tests_field_present` (deterministic, automatic_candidate): For PM plans, share of PR blocks with a non-empty tests field that names more than restated feature words (content-word overlap with the description below a threshold).

**Fixtures.** `fixtures/verifiability_boundary.json`, `fixtures/verifiability_rollback_metrics.json`. May also move: `clarity_vague_quantity`

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

**Example, stronger** ([python/peps pull request 4050: PEP 661, add missing sections](https://github.com/python/peps/pull/4050), PEP 661 between Specification and Reference Implementation, before and after the pull request). The pull request, titled 'Add missing sections', adds sections PEP 1 requires.

> Ordering comparisons are undefined for sentinel objects.
>
>
> Backwards Compatibility
> =======================
>
> While not breaking existing code, adding a new "sentinels" stdlib module could
> cause some confusion with regard to existing modules named "sentinels", and
> specifically with the "sentinels" package on PyPI.
>
> The existing "sentinels" package on PyPI [10]_ appears to be abandoned, with
> the latest release being made on Aug. 2016.  Therefore, using this name for a
> new stdlib module seems reasonable.
>
> If and when this PEP is accepted, it may be worth verifying if this has indeed
> been abandoned, and if so asking to transfer ownership to the CPython
> maintainers to reduce the potential for confusion with the new stdlib module.
>
>
> How to Teach This
> =================
>
> The normal types of documentation of new stdlib modules and features, namely
> doc-strings, module docs and a section in "What's New", should suffice.
>
>
> Security Implications
> =====================
>
> This proposal should have no security implications.
>
>
> Reference Implementation
> ========================

**Example, weaker** ([python/peps pull request 4050: PEP 661, add missing sections](https://github.com/python/peps/pull/4050), PEP 661 between Specification and Reference Implementation, before and after the pull request)

> Ordering comparisons are undefined for sentinel objects.
>
>
> Reference Implementation
> ========================

**Score anchors.** 1: Required structure missing; tools or readers relying on it would fail. 3: Mostly conformant; some required fields or sections missing. 5: Fully conformant, with deviations only where they serve the reader.

**Candidate measures** (readiness: automatic_candidate).

- `judge_genre` (judge, needs_calibration): Rubric judge score and paired preference.
- `template_section_presence` (deterministic, automatic_candidate): Required-section checklist per document_kind (from the process templates in references.json), heading-matched with synonyms.
- `pm_plan_parse` (deterministic, automatic_candidate): pm_core.plans.parser.parse_plan_prs returns at least one PR, every PR has non-empty description/tests/files, and depends_on resolves.

**Fixtures.** `fixtures/genre_missing_pep_sections.json`

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

**Example, stronger** ([IETF draft-ietf-pce-stateful-pce-vendor revisions -10 and -11](https://www.ietf.org/archive/id/draft-ietf-pce-stateful-pce-vendor-11.txt), Section 2, revision -10 (weaker) and -11 (stronger)). Section 1.2 already expanded RBNF; a reviewer flagged the repetition and the next revision stopped re-expanding it (it kept the sentence, so the fix is partial).

> The message formats in this document are specified using RBNF encoding as specified in [RFC5511].

**Example, weaker** ([IETF draft-ietf-pce-stateful-pce-vendor revisions -10 and -11](https://www.ietf.org/archive/id/draft-ietf-pce-stateful-pce-vendor-11.txt), Section 2, revision -10 (weaker) and -11 (stronger))

> The message formats in this document are specified using Routing Backus-Naur Format (RBNF) encoding as specified in [RFC5511].

**Score anchors.** 1: Restarts or repeats the prefix, or ignores the terms and decisions it established. 3: Continues but with some repetition, redefinition or a gap. 5: Seamless continuation in content and structure.

**Candidate measures** (readiness: automatic_candidate).

- `judge_continuity` (judge, needs_calibration): Rubric judge with the prefix in view; calibration must report sensitivity to style match separately.
- `prefix_repetition` (deterministic, automatic_candidate): Share of content-word 5-grams in the section that also occur in the prefix.
- `established_term_reuse` (deterministic, automatic_candidate): Of terms defined or emphasised in the prefix that the section's topic needs, share used verbatim rather than renamed.
- `style_distance` (deterministic, automatic_candidate, bias covariate): Burrows's Delta between prefix and section; recorded to measure how much judges reward style match, never scored as quality.

**Fixtures.** `fixtures/continuity_repeats_prefix.json`
<!-- END GENERATED -->

## References

See [references.json](references.json) for full citations, URLs and what each source was used for.
