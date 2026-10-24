You are evaluating two documents written for the same brief.{{document_kind_line}} They are labelled A and B only to tell them apart; neither the labels nor their order says anything about who wrote them.

Score each document on each dimension below, using that dimension's definition and score anchors. Before scoring a dimension, quote or point to the passages your judgment rests on.

- Judge content, not length.
- Material the brief does not mention is not a fault by itself.

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

Scores are integers from 1 to 5; 2 and 4 fall between the anchors. "preference" is "A", "B" or "tie" for that dimension alone. "overall_preference" is your overall judgment of which document better serves its reader, made separately from the dimension scores.
