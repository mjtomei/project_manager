You are evaluating one document written for the brief below.{{document_kind_line}}

Judge the document on the quality dimensions below, one dimension at a time, against the score anchors given for each. There is no other document to compare it with, and nothing about the document tells you who wrote it. Do not try to guess where it came from.

Rules:
- Score what the text does for its intended reader, not its length. A long document is not complete and a short one is not concise unless the content shows it.
- Judge fidelity and coverage against the brief{{material_rule}}. Useful elaboration that is consistent with the brief is not a fault, even when the brief never mentions it; text that contradicts the brief, or presents new material as already agreed, is.
- Before scoring a dimension, quote or point to the passages your judgment rests on.
- Keep dimensions separate. A fault belongs to the dimension whose definition it violates; do not let one fault lower every score.
- Use the whole scale. A 5 means the anchor for 5 describes the document; do not give 4 or 5 by default.

{{brief_block}}{{material_block}}
## Document

<document>
{{document}}
</document>

## Dimensions

{{dimension_block}}

## Output

Reply with a single JSON object and nothing else, in this shape:

{{output_schema}}

Scores use 1 to 5 with the anchors given for each dimension (2 and 4 fall between them). "overall_score" is your separate judgment of how well the document serves the brief's reader, on the same 1 to 5 scale; it is not an average of the dimension scores.
