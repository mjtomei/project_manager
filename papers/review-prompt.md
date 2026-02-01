# Automated Whitepaper Review Prompt

You are reviewing a whitepaper — a persuasive technical proposal intended to convince practitioners, funders, and policymakers to adopt a specific architecture. This is not a traditional academic paper reporting empirical results. Calibrate accordingly: the standard is whether the argument is sound, well-supported, and actionable, not whether it contains novel empirical contributions.

## Review the following document and produce a structured review covering:

### 1. Argument Strength
For each major claim in the paper:
- Is the claim supported by evidence, reasoning, or citation?
- Are there obvious counterarguments the paper doesn't address?
- Where does the paper assert rather than argue?
- Rate each section's argument quality (strong / adequate / weak / unsupported)

### 2. Evidence and Citation Gaps
- Are cost figures and empirical claims properly sourced?
- Are sources of varying rigor clearly distinguished?
- What claims need stronger or additional citations?
- What relevant literature is missing?

### 3. Logical Gaps and Weak Links
- Identify logical jumps between premises and conclusions
- Flag any circular reasoning or question-begging
- Note where the paper conflates correlation with causation, or possibility with inevitability
- Identify the single weakest argument in the paper

### 4. Counterarguments Not Addressed
- What would a sophisticated skeptic say?
- What are the strongest objections to the proposal?
- Does the Limitations section adequately cover the real risks?

### 5. Structural and Rhetorical Assessment
- Does the paper build its case in the right order?
- Are sections the right length relative to their importance?
- Is the abstract faithful to the actual content?
- Does the conclusion follow from the argument?

### 6. Actionability
- Could a reader implement the proposal from this paper alone?
- What practical details are missing?
- What would make this more convincing to a specific audience (funder, engineer, policymaker)?

### 7. Line-Level Issues
- Flag specific passages that are unclear, overwritten, or could be cut
- Note any inconsistencies between sections
- Identify redundancies

### 8. Summary Assessment
- One paragraph: what is the paper's strongest contribution?
- One paragraph: what is its most critical weakness?
- Ordered list of the three highest-priority revisions

---

**Calibration notes:**
- Do not penalize the paper for being a design proposal rather than empirical research. The paper knows this and says so.
- Do penalize unsupported assertions, missing engagement with counterarguments, and logical gaps.
- Be specific: cite line numbers or quote the text you're critiquing.
- Be direct. Do not soften criticism. The author wants to know what's wrong.
