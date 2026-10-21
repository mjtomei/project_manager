# pr-44f807f — Technical document quality rubric: QA spec

The PR adds a research artifact, not a pm feature: a rubric (`experiments/plan-writing/rubric/`)
with a narrative document (`rubric.md`, partly generated), machine-readable sources
(`dimensions.json`, `references.json`), two judge-prompt templates, 15 strong/weak fixtures,
and a stdlib-only module `experiments/plan-writing/rubric.py` with a small CLI
(`--render <case type|fixture id>`, `--write-doc`). It also leaves a handoff note on the
downstream runner PR (`pr-8df6472`, "Document evaluation runner and evaluator calibration").

The users are (a) a researcher reading the rubric and maintaining it, (b) the author of the
runner PR who imports `rubric.py`, renders judge prompts and validates judge replies, and (c) a
pm user whose plan documents the `genre_conventions` dimension is about.

## Setup

- Clone the branch; Python 3 and pytest available. No network or model access is required.
- The module lives in a hyphenated directory, so a runner script loads it by path
  (`importlib.util.spec_from_file_location`) rather than `import`.
- For the pm-plan story, install pm (`./install.sh --local`) and create a throwaway pm project
  in a temp directory (see `tui-manual-test.md` for the throwaway-project pattern).

## Requirements

R1. Given a fresh checkout, when the researcher opens `rubric.md`, then it contains a survey,
derivation, concern mapping table, judge-template description, calibration section, a
dimension reference with one section per dimension in `dimensions.json` (13 dimensions), and a
references list; every relative link in it resolves to a file in the repo.

R2. Given a fresh checkout, when the researcher regenerates the reference (`--write-doc`), then
`rubric.md` is byte-identical to the committed file (generated part is in sync with the JSON).

R3. Given the researcher edits a dimension in `dimensions.json` (e.g. its definition or a
candidate measure), when they run `--write-doc`, then only the generated block between the
`GENERATED` markers changes, reflecting the edit, and hand-written sections above and below are
untouched.

R4. Given every dimension, when the researcher reads its section, then it shows a definition,
at least one source linking to an entry in `references.json` (with URL), strong and weak
examples, detection guidance, score anchors, candidate measures with a status, a readiness
value (`automatic_candidate` or `calibration_required`), and at least one fixture.

R5. Given the four concerns (padding, premature implementation detail, poor progression, lost
requirements) plus fidelity, when the researcher reads the concern table and fixture list, then
each concern maps to a primary dimension and at least one fixture is tagged with it.

R6. Given a case type or fixture id, when the user runs `rubric.py --render <x>` (from any cwd),
then a complete judge prompt is printed: no `{{...}}` left, the brief (whole-document) or
prefix (continuation) is shown, the two candidates appear as A and B, and the dimension list
contains only dimensions that apply to that case type (no `continuity` in whole-document).

R7. Given a rendered prompt, when the user inspects it, then nothing reveals which candidate is
strong/weak or where it came from: no fixture id, `expected`, `notes`, `held_constant`,
"strong"/"weak" labels, source URLs or "original/generated" wording.

R8. Given a runner script outside the repo dir in an environment without `bs4`, when it loads
`rubric.py` by path and calls `render_judge` for each fixture with both A/B orderings and with
a dimension subset, then prompts render, swapping order swaps only the candidate slots, and the
subset limits the dimension block and output schema to the listed ids.

R9. Given candidate or brief text containing template-like or regex-like content (`{{brief}}`,
`{{section_a}}`, `$1`, `\1`, `\g<0>`, unicode), when it is rendered, then that text appears
verbatim exactly once in its slot and is not expanded.

R10. Given a judge reply parsed as JSON, when the runner validates it against the rendered
dimension ids, then a reply that follows the output schema has no problems and malformed
replies list specific problems (see edge cases).

R11. Given the `genre_pm_plan_fields` fixture, when a pm user loads its strong variant as a plan
file (`pm plan load`), then pm creates two PRs with the second depending on the first; when
they load the weak variant, pm reports no PRs found — matching the fixture's claim.

R12. Given the runner PR `pr-8df6472`, when the user lists its notes, then a note describes the
rubric interface (import by path, `render_judge`, `validate_judgment`, fixtures, bias
covariates).

R13. Given a fresh checkout, when the user runs `pytest tests/test_doc_rubric.py`, then all
tests pass without network.

## Edge cases

E1. `--render` with an unknown id → argparse error listing valid choices, non-zero exit.
E2. No flags → prints nothing, exit 0 (acceptable; no crash).
E3. `render_judge("whole_document", ...)` with a prefix, without a brief, or with an empty brief
→ ValueError; `continuation` with a brief or without a prefix → ValueError.
E4. Empty candidate A or B → ValueError "Both candidates are required".
E5. Unknown case type → ValueError; a dimension id not applicable to the case type (e.g.
`continuity` for whole_document, or a typo) → ValueError naming it.
E6. Continuation without `section_request` → prompt renders with no "The writers were asked"
sentence; without `document_kind` → no "Document kind" sentence; no dangling whitespace
artifacts like double spaces breaking sentences.
E7. `validate_judgment` problems for: non-object reply; missing `dimensions`; a missing
dimension; an unexpected dimension; duplicate rows; a row whose `dimension` is a list/number;
scores 0, 6, 3.0, "3", true; preference "a" or "both"; `evidence` a string; missing or invalid
`overall_preference`.
E8. `rubric.md` with the GENERATED markers removed → `--write-doc` fails loudly and does not
truncate or blank the file.
E9. A dimension citing a reference id absent from `references.json` → `--write-doc` fails and
the test suite reports it; a dimension missing its heading in rubric.md → test suite fails.
E10. Concurrent use: many `--render` processes and runner threads in parallel produce output
identical to a sequential baseline; concurrent `--write-doc` runs (and pytest runs reading
`rubric.md` while it is rewritten) leave `rubric.md` identical to committed; any transient
read failures during overlap are reported, not hidden.

## Pass/Fail criteria

Pass: every Then above observed; regenerated doc in sync; prompts blinded and complete; errors
raised with clear messages and no partial writes; pm plan load behaves as the genre fixture
claims; parallel runs deterministic. Fail: leftover placeholders, leakage of fixture labels or
expected direction, re-expansion of document text, `continuity` in whole-document prompts, a
valid reply flagged or an invalid one passed, `--write-doc` corrupting `rubric.md`, broken
links, the genre fixture's claim not holding in pm.

## Ambiguities (resolved)

- *User surface.* There is no UI; the surfaces are the CLI (`--render`, `--write-doc`), the
  documented library API consumed by the runner PR, the Markdown document, and pm's plan loader
  for the genre fixture. Scenarios drive these as a researcher/runner author would, not by
  grepping the JSON.
- *`--render` always puts the strong variant in slot A.* It is a debugging aid; blinding and
  order randomisation are the runner's job (documented). Not a defect; the runner story swaps
  order itself.
- *Concurrent `--write-doc`.* Writes are non-atomic `write_text`; concurrent regeneration is not
  a supported workflow, so a race that self-heals (final file correct) passes, while a final
  corrupted file or a pytest crash on a mid-write read is reported as a finding (low severity).
- *Live judge models.* Not required; a hand-written reply exercises `validate_judgment`. If a
  Claude CLI happens to be available, feeding one rendered prompt to it is optional extra
  evidence, never a pass/fail gate.
