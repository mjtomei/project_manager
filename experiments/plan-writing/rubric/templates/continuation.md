You are evaluating two candidate next sections for the same partial document.{{document_kind_line}} The prefix below is the document up to a section boundary; each candidate is meant to be the section that comes next.{{section_request_line}}

Judge each candidate on the quality dimensions below, one dimension at a time. The candidates are labelled A and B only to tell them apart; the labels and their order carry no information about who wrote them or which is expected to be better. Either candidate may be better on any dimension, and the two may differ in direction across dimensions. Do not try to guess where a candidate came from.

Rules:
- Score what the section does for a reader of this document, not its length.
- Judge fidelity against the prefix: names, numbers, decisions and scope it has established. Useful elaboration consistent with the prefix is not a fault.
- Judge continuity on content and structure: picking up where the prefix stopped, reusing its terms and decisions, not repeating it, not skipping ahead. Do not reward a candidate for imitating the prefix author's personal style (word choice, sentence rhythm, punctuation habits); a different, clear style is not a fault.
- Before scoring a dimension, quote or point to the passages your judgment rests on.
- Where the dimension guidance below mentions the brief, read it as the prefix together with what the writers were asked for this section.
- Keep dimensions separate. A fault belongs to the dimension whose definition it violates; do not let one fault lower every score.

## Prefix

<prefix>
{{prefix}}
</prefix>

## Candidate A

<section_a>
{{section_a}}
</section_a>

## Candidate B

<section_b>
{{section_b}}
</section_b>

## Dimensions

{{dimension_block}}

## Output

Reply with a single JSON object and nothing else, in this shape:

{{output_schema}}

Scores use 1 to 5 with the anchors given for each dimension (2 and 4 fall between them). "preference" is "A", "B" or "tie" for that dimension alone. "overall_preference" is your separate judgment of which candidate better continues this document for its reader; it is not an average of the dimension scores.
