You are evaluating one candidate next section for a partial document.{{document_kind_line}} The prefix below is the document up to a section boundary; the candidate is meant to be the section that comes next.{{section_request_line}}

Judge the candidate on the quality dimensions below, one dimension at a time, against the score anchors given for each. There is no other candidate to compare it with, and nothing about the candidate tells you who wrote it. Do not try to guess where it came from.

Rules:
- Score what the section does for a reader of this document, not its length.
- Judge fidelity against the prefix: names, numbers, decisions and scope it has established. Useful elaboration consistent with the prefix is not a fault.
- Judge continuity on content and structure: picking up where the prefix stopped, reusing its terms and decisions, not repeating it, not skipping ahead. Do not reward the candidate for imitating the prefix author's personal style (word choice, sentence rhythm, punctuation habits); a different, clear style is not a fault.
- Before scoring a dimension, quote or point to the passages your judgment rests on.
- Where the dimension guidance below mentions the brief, read it as the prefix together with what the writer was asked for this section.
- Keep dimensions separate. A fault belongs to the dimension whose definition it violates; do not let one fault lower every score.
- Use the whole scale. A 5 means the anchor for 5 describes the section; do not give 4 or 5 by default.

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

Scores use 1 to 5 with the anchors given for each dimension (2 and 4 fall between them). "overall_score" is your separate judgment of how well the candidate continues this document for its reader, on the same 1 to 5 scale; it is not an average of the dimension scores.
