You are evaluating one document written for the brief below.{{document_kind_line}}

Score the document on each dimension below, using that dimension's definition and score anchors. Before scoring a dimension, quote or point to the passages your judgment rests on.

- Judge content, not length.
- Material the brief does not mention is not a fault by itself.

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

Scores are integers from 1 to 5; 2 and 4 fall between the anchors. "overall_score" is your overall judgment of how well the document serves its reader, on the same scale, made separately from the dimension scores.
