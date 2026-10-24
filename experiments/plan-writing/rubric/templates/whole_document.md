You are evaluating two documents written for the same brief.{{document_kind_line}}

Judge each document on the quality dimensions below, one dimension at a time. The documents are labelled A and B only to tell them apart; the labels and their order carry no information about who wrote them or which is expected to be better. Either document may be better on any dimension, and the two may differ in direction across dimensions. Do not try to guess where a document came from.

Rules:
- Score what the text does for its intended reader, not its length. A longer document is not more complete and a shorter one is not more concise unless the content shows it.
- Judge fidelity and coverage against the brief{{material_rule}}. Useful elaboration that is consistent with the brief is not a fault, even when the brief never mentions it; text that contradicts the brief, or presents new material as already agreed, is.
- Before scoring a dimension, quote or point to the passages your judgment rests on.
- Keep dimensions separate. A fault belongs to the dimension whose definition it violates; do not let one fault lower every score.

{{brief_block}}{{material_block}}
## Document A

<document_a>
{{document_a}}
</document_a>

## Document B

<document_b>
{{document_b}}
</document_b>

## Dimensions

{{dimension_block}}

## Output

Reply with a single JSON object and nothing else, in this shape:

{{output_schema}}

Scores use 1 to 5 with the anchors given for each dimension (2 and 4 fall between them). "preference" is "A", "B" or "tie" for that dimension alone. "overall_preference" is your separate judgment of which document better serves the brief's reader; it is not an average of the dimension scores.
