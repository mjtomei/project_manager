You are evaluating two candidate next sections for the same partial document.{{document_kind_line}} The prefix below is the document up to a section boundary; each candidate is meant to be the section that comes next.{{section_request_line}} The candidates are labelled A and B only to tell them apart; neither the labels nor their order says anything about who wrote them.

Score each candidate on each dimension below, using that dimension's definition and score anchors. Before scoring a dimension, quote or point to the passages your judgment rests on. Where a definition refers to the brief, read it as the prefix together with what the writers were asked for this section.

- Judge content, not length.
- Material the prefix does not mention is not a fault by itself.
- Do not reward a candidate for imitating the prefix author's personal style.

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

Scores are integers from 1 to 5; 2 and 4 fall between the anchors. "preference" is "A", "B" or "tie" for that dimension alone. "overall_preference" is your overall judgment of which candidate better continues this document for its reader, made separately from the dimension scores.
