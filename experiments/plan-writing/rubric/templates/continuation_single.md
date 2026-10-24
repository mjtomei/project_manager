You are evaluating one candidate next section for a partial document.{{document_kind_line}} The prefix below is the document up to a section boundary; the candidate is meant to be the section that comes next.{{section_request_line}}

Score the candidate on each dimension below, using that dimension's definition and score anchors. Before scoring a dimension, quote or point to the passages your judgment rests on. Where a definition refers to the brief, read it as the prefix together with what the writer was asked for this section.

- Judge content, not length.
- Material the prefix does not mention is not a fault by itself.
- Do not reward the candidate for imitating the prefix author's personal style.

## Prefix

<prefix>
{{prefix}}
</prefix>

## Candidate

<section>
{{section}}
</section>

## Dimensions

{{dimension_block}}

## Output

Reply with a single JSON object and nothing else, in this shape:

{{output_schema}}

Scores are integers from 1 to 5; 2 and 4 fall between the anchors. "overall_score" is your overall judgment of how well the candidate continues this document for its reader, on the same scale, made separately from the dimension scores.
