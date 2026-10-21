# pr-44f807f — Technical document quality rubric: implementation spec

## Requirements

1. **Survey and derived dimensions.** Survey published rubrics, standards, process
   templates and evaluation literature for technical, design and planning
   documents, and derive a general set of quality dimensions for
   `pm/plans/plan-doc-eval.md` ("Before calibrating judges, survey published
   quality rubrics … derive a general, referenced set of quality dimensions with
   definitions and detection guidance"). Sources to draw on, chosen to match the
   corpus in `experiments/plan-writing/sources.json` (PEPs, Rust RFCs, KEPs, Go
   proposals, IETF RFCs, Oxide RFDs, Shape Up pitches, NASA concept studies) as
   well as general standards: ISO/IEC/IEEE 29148 and INCOSE GtWR (requirement
   quality characteristics), ISO/IEC/IEEE 42010 (architecture rationale),
   ISO 24495-1 and the Federal Plain Language Guidelines, the AAC&U Written
   Communication VALUE rubric and 6+1 Traits, the corpus's own process
   documents (PEP 1, Rust RFC template, KEP template, Go proposal README,
   RFC 7322, RFC 4101, RFC 3552, Oxide RFD 1, Shape Up), Google's design-doc
   practice, Gopen & Swan, Grice, and the LLM-evaluation literature (SummEval,
   G-Eval, FActScore, SummaC, MT-Bench judge biases, verbosity bias).
   Each dimension carries: id, name, definition, references (≥1 external),
   good and weak examples, detection guidance, judge question with score
   anchors, applicable case types, and candidate measures.

2. **Concern mapping.** Map the four previously identified concerns — padding,
   premature implementation detail, poor progression, lost requirements — and
   fidelity onto those dimensions, as placements within the general set rather
   than the whole measure. Source of the concerns and the "useful elaboration
   is not wrong" criterion: `pm/docs/plan-session-sources-2026-10-19.md`
   ("Obvious material or text that adds no planning value is a primary
   readability problem…"; "distracting material draws his review away from
   important planning decisions").

3. **Rubric document.** `experiments/plan-writing/rubric/rubric.md`: survey,
   derivation, per-dimension sections, concern mapping, measure-readiness table,
   known judge biases. Machine-readable source of truth:
   `rubric/dimensions.json` (dimensions + concern mapping) and
   `rubric/references.json` (bibliography with URL/identifier, kind, year).

4. **Judge templates.** `rubric/templates/whole_document.md` and
   `rubric/templates/continuation.md`, rendered by
   `experiments/plan-writing/rubric.py` (`load_rubric()`, `render_judge()`).
   Paired and blinded (Document A / Document B, no origin labels or provenance);
   the continuation template shows the prefix; output contract is per-dimension
   JSON so dimensions stay distinct.

5. **Fixtures.** `rubric/fixtures/*.json`: for every dimension at least one
   fixture with a brief (or prefix), a strong and a weak variant that differ
   mainly on the target dimension, and the expected direction. Fixtures tagged
   with the concern they exercise must exist for padding, premature
   implementation detail, poor progression, lost requirements (and fidelity).

6. **Measure readiness.** Each candidate measure is marked
   `automatic_candidate` (computable without a judge model: parsers, section
   checks, n-gram redundancy, NLI-style checks are listed as model-assisted)
   or `needs_calibration` (judge-scored). Each dimension's
   `measure_readiness` summarises this. Nothing is a validated score yet.

7. **Tests.** `tests/test_doc_rubric.py`: every dimension has definition,
   example, ≥1 external reference that resolves in references.json, candidate
   measure, readiness flag; every dimension appears in rubric.md; fixtures exist
   for each dimension and each of the four concerns; both templates render
   (whole-document from a brief, continuation from a prefix) with no unfilled
   placeholders, and rendering fixtures works.

## Implicit requirements

- The runner PR (pr-… "Document evaluation runner and evaluator calibration")
  consumes these artifacts, so the JSON schema and `render_judge()` signature
  must be stable and documented; the module must import without the
  `bs4` dependency that `collect.py` needs.
- Tests must import `experiments/plan-writing/rubric.py` although the
  directory name contains a hyphen: load via `importlib.util.spec_from_file_location`.
- Templates must not leak origin: no source id, URL, provenance or
  "original/generated" wording; the renderer must take candidates only as
  neutral A/B slots (order randomization is the runner's job).
- Substitution must be single-pass so `{{…}}` or `$` inside document text is
  never re-expanded; unknown or missing placeholders raise.
- Elaboration must be protected: fidelity and concision guidance must state
  that consistent, useful elaboration beyond the brief is not penalised.
- Continuation judges see the prefix; the continuity dimension rewards content
  and structural continuity, and explicitly tells judges not to reward
  idiosyncratic stylistic mimicry (the plan flags stylistic continuity as a bias
  toward the original author to be measured, not rewarded).
- PM plan cases need the genre dimension to cover required plan fields and
  dependency semantics (plan-doc-eval "Preserve user intent, required plan
  fields and dependency semantics"); `pm_core/plans/parser.py` is the existing
  automatic check for PM plan PR blocks.

## Ambiguities (resolved)

- *"Candidate automatic measures" vs "need calibration evidence".* Resolution:
  per measure `status` ∈ {`automatic_candidate`, `needs_calibration`}; every
  dimension has at least one judge measure (`needs_calibration`); dimensions
  that also have a judge-free measure get `measure_readiness:
  automatic_candidate`, the rest `calibration_required`. Automatic candidates are
  still diagnostics until the calibration PR checks them against judges. A third
  status, `deferred`, marks measures that need inference-engine access (NLI or
  classifier probabilities) and are outside the first PRs; bias covariates
  (`role: bias_covariate`, e.g. `length_ratio`, `style_distance`) are
  automatic but do not make a dimension `automatic_candidate`.
- *Pointwise vs paired judging.* Plan specifies blinded paired evaluation;
  templates are paired, but ask for a 1–5 score per document per dimension plus
  a per-dimension preference, so pointwise use stays possible. An overall
  preference is requested separately and never computed from dimension scores.
- *Fidelity as a fifth concern.* The task lists fidelity next to the four
  concerns; it is mapped as its own dimension and given a concern-tagged fixture,
  while tests require the four named concerns.
- *Format of the rubric document.* Hand-written Markdown narrative plus JSON
  source of truth; a test keeps them in sync (every dimension id has a heading).
- *How the continuation request is phrased to judges.* The case catalog PR has
  not defined it; the template takes an optional `section_request` and an
  optional `document_kind`.

## Edge cases

- Dimensions that only make sense for one track (continuity → continuation
  only) carry `applies_to`; templates list only applicable dimensions.
- Requirement coverage in continuations is measured against commitments the
  prefix makes, not a brief.
- Fixture variants are short; length differences are deliberate only in the
  padding fixture, so other fixtures keep lengths similar to avoid confounding
  with verbosity bias.
- In continuations, each prefix-related fault has one owner: contradicting the
  prefix is fidelity, repeating or restarting it is continuity (concision judges
  filler within the section only), so fixtures for one do not move the other.
- No network or model calls in tests; reference URLs are not fetched in tests.
