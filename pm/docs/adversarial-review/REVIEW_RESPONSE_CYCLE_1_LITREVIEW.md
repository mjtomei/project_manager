# Review Response — Cycle 1 (literature-review.md)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_1_LITREVIEW.md`

This response works through the reviewer's findings, marks each agree / partial / disagree, and specifies the edit (or counter-argument) before any text changes land in `literature-review.md`. Where the reviewer is right, we say so plainly; where the framing is wrong, we push back with substance.

A meta-framing thread runs through several findings — particularly the Huang et al. and Pan et al. critiques — and is worth stating once before working through items:

> **The plan is not asking the LLM to self-correct its reasoning in a vacuum.** Huang et al. 2023's finding is about *intrinsic* self-correction: the model receives no new information and is asked to improve its own reasoning trace. That's a real limitation and we'll cite it. But the plan's loops are categorically different. Each iteration *generates new data* — a regression test file on disk, a coverage report, a tool-use transcript, an integrity-audit allowlist check — and that data is external to the model's reasoning. The LLM is acting as a *generator of artifacts that get evaluated by mechanical systems* (test runners, coverage tools, transcript audits) and that *compound* across runs. The compounding regression library, the evidence artifacts in `pr-eb450a0`, the coverage gates in `pr-b42059d`/`pr-8ed578d`, and the audit report in `pr-e2b7fdf` are all instances of the same pattern: produce concrete data, check it against an external standard, and let it constrain the next iteration. We're not expecting reasoning improvement *ex nihilo*; we're treating the LLM as a source of legible, checkable data, which is a different problem with a different failure-mode profile than what Huang et al. measured.

This framing matters for at least three of the reviewer's findings and is incorporated into the edits below.

---

## Hard errors (all agree, no nuance)

### 1. ImpossibleBench attribution — Zhong, not Wu

**Agree.** Outright error. Edit: replace all instances of "Wu et al. 2025" with "Zhong, Raghunathan, Carlini 2025" in §5 prose and references. arXiv ID 2510.20270 stays.

### 2. OpenHands SDK "72% on SWE-Bench Verified" — unsourced

**Agree.** The number is not in the abstract; either it's in the paper body and needs a page citation, or it came from a blog/leaderboard and should cite that. Edit: fetch the OpenHands SDK paper (arXiv:2511.03690) body and confirm the figure; if confirmed, add a section reference. If not, replace with the swebench.com leaderboard URL with a snapshot date.

### 3. "Roughly 80% of the technical lineage" — rhetorical flourish

**Agree.** This is exactly the kind of unfalsifiable handwave the methodology is supposed to catch. Edit: cut from the Conclusion. Replace with a concrete list of what the ten references *do* cover: "These ten cover the benchmark genealogy (1, 2), agent architecture (3, 4), self-improvement (5, 6), contamination and cheating (7, 8, 9), and the test-generation primitive (10) — the five threads the plan stitches together. They do not cover the watcher-architecture (Section 6) or test-double (Section 7) literature, which is treated separately."

### 4. Sainz et al. title capitalization

**Agree, minor.** Inline prose uses "in trouble"; reference list uses "in Trouble." Verified title has "in Trouble." Edit: fix the prose mention.

### 5. SWE-Bench venue "oral" designation

**Agree.** Either source the oral-designation claim from the ICLR 2024 acceptance list or drop the qualifier. Edit: keep "ICLR 2024," drop "(oral)" unless the program PDF can be cited.

---

## Missing references

### Huang et al. 2023, "Large Language Models Cannot Self-Correct Reasoning Yet" (arXiv:2310.01798, ICLR 2024)

**Agree to cite. Disagree with reviewer's framing of why.**

The reviewer treats this as the canonical Self-Refine rebuttal and an integrity issue for not citing it. Cite it — but the framing in our text needs to be specific about what Huang et al. *do* and *don't* show, because the naive reading would suggest the plan's loops are unsound.

Huang et al.'s result is about **intrinsic self-correction**: the model has only its prior output and is asked to improve it without new information. In that setting, performance often degrades. They explicitly distinguish this from settings with external feedback (tool calls, ground truth, oracle access), where self-correction can help.

The plan's loops are not intrinsic self-correction. The scenario quality supervisor (`pr-98f670e`) examines *the scenario session's tool-use transcript and captured outputs* — external data — not its own reasoning trace. The bug-fix flow (`pr-30588a7`, merged) requires a *failing test that demonstrates the bug* before any fix is attempted — external grounding. The capstone integrity audit (`pr-e2b7fdf`) walks the agent's actual tool calls against an allowlist — external check. The coverage gates (`pr-b42059d`, `pr-8ed578d`) measure code execution, not model self-assessment.

**Edit**: add Huang et al. 2023 to §4. Frame as: "Huang et al. 2023 'LLMs Cannot Self-Correct Reasoning Yet' establishes that LLMs given only their own prior reasoning often *degrade* on self-correction. The result is load-bearing but bounded — Huang et al. distinguish intrinsic self-correction from settings with external feedback, where self-correction reliably helps. The plan's loops are all in the second category: scenario captures (external), coverage measurements (external), failing-test grounding (external), tool-use transcripts (external). The plan is not relying on intrinsic reasoning improvement; it is relying on the LLM as a generator of legible, checkable artifacts that compound across runs. The compounding regression library (§3) is the concrete payoff."

### Pan et al. 2024, "Spontaneous Reward Hacking in Iterative Self-Refinement" (arXiv:2407.04549)

**Agree to cite. Partial agreement on the framing.**

Pan et al. show that when generator and evaluator share context, reward hacking emerges spontaneously. Relevant to `pr-98f670e` (scenario quality supervisor) because the supervisor and the scenario both run under the same Claude.

**Edit**: cite Pan et al. in §4, paired with Huang et al. Acknowledge that the same-model risk is real. But: the supervisor's design *does* separate context — the supervisor reads the scenario's captures and transcript after the fact via `--resume`; it is not in the scenario's loop. That is exactly Pan et al.'s recommended mitigation (context separation, not just bounded iteration). The cap-at-2 amendment limit is the secondary defense. Frame it that way rather than leaving it implicit.

### Agentless (Xia et al. 2024) and AutoCodeRover (Zhang et al. 2024)

**Agree.** Both belong in §2. Agentless is particularly important — it's the counter-design (no iterative tool use, no agent loop) that beats many agent designs on SWE-Bench Lite. Its existence makes the plan's loop-based design a *bet*, not a foregone conclusion. Worth a paragraph contrasting.

**Edit**: add a paragraph at the end of §2 about Agentless and AutoCodeRover as the explicit counter-design. Frame: "The plan's iterative-loop design is not the only credible approach to autonomous coding. Agentless deliberately removes the agent loop and beats many agent-based systems on SWE-Bench Lite by relying on careful retrieval + single-shot generation. AutoCodeRover uses AST-based program analysis to ground generation. Both are evidence that the design space is broader than the SWE-agent / OpenHands lineage, and the plan's commitment to a loop-based architecture should be understood as a deliberate bet, not a default."

### AgentSpec, AgentAuditor, Anthropic 2025 alignment-auditing-agents

**Agree, but with caveats per item.**

- **AgentSpec** (ICSE 2026): runtime enforcement for agents. Relevant to the plan's review/QA gate as a published peer. Edit: cite in §6.
- **AgentAuditor** (OpenReview 2025): memory-augmented LLM evaluator agents. Closer peer to the watcher review session (`pr-e84b43c`) than MetaGPT is. Edit: cite in §6.
- **Anthropic 2025 "Building and evaluating alignment auditing agents"**: agents that audit other agents. Closest published industrial work to the integrity audit. Edit: cite in §5, and reframe — *this is the closer peer to `pr-e2b7fdf` than ImpossibleBench is.* The reviewer is right that the current "ImpossibleBench is the closest peer" framing is misplaced.

### TestPilot (Schäfer et al., GitHub Next, 2023)

**Agree.** Conspicuous omission from §3 alongside CodaMosa. Edit: cite.

### EvalPlus / "Is Your Code Generated by ChatGPT Really Correct?" (Liu et al., NeurIPS 2023)

**Agree.** Already referenced under plan-002 (separate plan for benchmark expansion), but the contamination/correctness thread in §1 and §5 should cite it here too. Edit: add to §1 and §5 references.

### METR 2025 "Recent Frontier Models Are Reward Hacking"

**Agree.** Most current empirical data on the §5 threat model. Edit: cite alongside NIST CAISI in §5.

### SWE-Bench Multimodal

**Partial agreement.** Worth mentioning for completeness but not load-bearing for any plan PR. Edit: add a one-line mention in §1 alongside SWE-Bench Verified and SWE-Bench Pro.

### Reflexion full author list

**Agree.** Reference entry should be complete. Edit.

### Sapfix / Getafix and the program-repair-in-CI body of work

**Agree.** The reviewer is right that this is the closest academic peer to the bug-fix watcher and was missed entirely. Edit: add to §6, with a paragraph noting that automated program repair has a substantial literature (Le Goues et al.'s GenProg, Facebook's Sapfix/Getafix, more recent CodeLlama-based repair work) that pre-dates the LLM-coding-agent wave and provides the closest academic analog to a "watcher that drives PRs through fix → review → merge."

---

## Framing pushback (reviewer is right; we need to flip)

### "ImpossibleBench is the closest peer to the integrity audit"

**Agree to flip.** Reviewer is correct that NIST CAISI is closer for the *runtime-internet* threat model and Anthropic 2025 alignment-auditing-agents is closer for the *supervisor architecture*. ImpossibleBench is closest only on the narrow "LLM exploits the scoring surface" axis.

**Edit**: rewrite §5's "closest peer" paragraph. New framing: "The plan's integrity audit has *three* near-peer literatures. NIST CAISI's transcript-review work catalogs the runtime-internet threat model and demonstrates an LLM-as-auditor pipeline against it — closest on the threat-model axis. Anthropic 2025's alignment-auditing-agents shows agents that audit other agents at scale — closest on the supervisor-architecture axis. ImpossibleBench measures cheating-propensity in coding agents and reports the most directly relevant empirical numbers (monitor sensitivity in the 42–50% range on complex multi-file cases) — closest on the empirical-grounding axis. None of these is a complete peer; the audit in `pr-e2b7fdf` combines elements of all three."

### "Watcher-architecture academic literature is thin"

**Agree to soften and reframe.**

The reviewer is right that the search was incomplete. AgentSpec, AgentAuditor, program-repair-in-CI, SkillProbe, and the auditing-agents work all exist. The honest version is: "academic work on cooperating watchers in a continuous-quality pipeline is sparse, but adjacent literatures — runtime enforcement (AgentSpec), evaluator agents (AgentAuditor), automated program repair (Sapfix, Getafix, GenProg), and alignment auditing (Anthropic 2025) — collectively cover the watcher-architecture design space. The plan's specific choice — three independent watchers with shared work-log substrate, dynamic priority, no persisted priority field — sits at an intersection these literatures don't fully address, but the under-explored region is narrower than 'no peer-reviewed paper.'"

**Edit**: rewrite §6's "thin" passages.

### "Industry-heavy" cover for incomplete search in §6 and §7

**Agree.** Redo the search; remove the "industry-flavored but architecturally informative" framing. Either cite academic work or admit explicitly which search terms were tried and what was found.

**Edit**: §6 — cite the program-repair-in-CI work, AgentSpec, AgentAuditor. §7 — search for LLM-mock and record-replay-for-distributed-systems academic work; if the search remains thin, list the queries used so the gap is auditable.

---

## Specific empirical claims requiring sourcing

| Claim | Source needed |
|---|---|
| "OpenHands has become the de facto baseline for SWE-Bench Verified" | swebench.com leaderboard with snapshot date |
| "Claude Opus 4.7 with mini-swe-agent currently tops the ProgramBench leaderboard" | programbench.com leaderboard with snapshot date |
| "ImpossibleBench monitor sensitivity 42–50%" | Specific table/section in arXiv:2510.20270 |
| "Devin first to claim a fully autonomous 'junior engineer' framing" | Drop "first" — unsupportable without contemporaneous date check |
| OSS-Fuzz analogy | Serebryany 2017 USENIX paper or OSS-Fuzz GitHub README |

**Edit**: source each or remove. Default to including the snapshot date in any leaderboard reference.

---

## Citation graph walk

**Agree.** The reviewer's diagnosis is correct: the ten-reference set is a first-tier seed list, not a graph traversal.

**Edit**: do a real walk. Start from SWE-Bench, Self-Refine, Reflexion, ImpossibleBench. For each, follow forward citations (Semantic Scholar's "Cited by") and backward references. Report what was added vs. what was already present. Acceptable to budget this — a full walk could take hours — but the review should be transparent about how many citations were followed and at what depth.

---

## Mischaracterized prior work

### Reflexion — under-credited memory buffer

**Agree.** The plan's work-log pattern is precisely Reflexion's episodic memory contribution. Current text gives Reflexion brief credit but doesn't connect the dot to the plan's `pm/watchers/*.log` substrate.

**Edit**: add a sentence in §4 explicitly attributing the work-log-as-cross-tick-memory pattern to Reflexion's verbal-RL design.

### SWE-agent — under-credited paradigm-defining contribution

**Agree.** Edit: extend §2's SWE-agent treatment with a sentence noting that Yang et al. effectively defined the modern coding-agent paradigm and that the plan's BaseWatcher prompt-builder lineage is downstream regardless of whether the connection was explicit.

### CodaMosa — under-credited general pattern

**Agree.** Edit: extend §3's CodaMosa treatment with a sentence connecting "LLM as escape valve for stuck classical algorithms" to the plan's coverage-driven scenario growth (`pr-c2397e2`).

---

## Structure and readability

### "Non-expert readable" failures

**Agree.** Edit each:

- §1 first ACI use: define inline on first mention, refer back later.
- §4 actor-critic: add a one-sentence gloss for readers without RL background.
- §5 AST plagiarism detection: explain why this technique is the right tool for contamination measurement.
- §5 "Inspect-based": expand on first mention — "Inspect, AISI/Anthropic's open eval framework."
- §4 "verifier-guided generation": cite or remove.

### Verbosity

**Agree on §1 paragraphs 1–2 compression and the Devin paragraph trim.** Edit both. The Conclusion repetition is a separate issue and is addressed under "Hard errors #3" above (cut the 80% claim).

### Needs-more-space

**Agree on all three** — threat model (§5), priority-without-state (§6), Fuzz4All autoprompting analogy (§3). Edit each.

### Repetition (should be / shouldn't be)

**Agree.** Edit: cut the 42–50% number from the Conclusion (kept once in §5). Add a Conclusion callback to the compounding regression library. Foreshadow the runtime-vs-pretraining contamination distinction in the Intro.

### Structural changes

- **Merge §6 and §7**: agree. New section title "Operational Infrastructure (academic + industry)". Two subsections within, but a single honest framing.
- **Promote integrity-audit threat model to a stand-alone subsection in §5**: agree.
- **Add the "Where this plan sits" diagram in Conclusion**: agree to attempt. ASCII diagram is feasible inline; if it can't be made readable in plain Markdown, ship as a separate `lit-review-figures.md` file.

### Section flow / bridges

**Agree.** Add the two suggested bridges between §4/§5 and §5/§6.

### Hooks

**Agree.** Rewrite the §1, §5, and Conclusion openings with the reviewer's suggested hook framing.

### Figures

- **Benchmark comparison table** (§1): agree, build it. Columns: year, network access, contamination defense, task granularity, evaluator type.
- **Plan-placement diagram** (Conclusion): agree to attempt in ASCII; failing that, defer to a separate file.
- **Self-critique pattern evolution** (§4): agree to attempt. Self-Refine → Reflexion → ChatUniTest GVR → plan's QA quality supervisor.

---

## Items the reviewer overstated or got wrong

These are few. Most of the review is well-grounded.

### "Not citing Huang et al. 2023 is a research-integrity issue, not an oversight"

**Partial pushback.** Citing it is right and we will. But "research-integrity issue" is too strong for a review that is explicitly framed as a non-expert-readable map of a research lineage to support an engineering plan. The omission is a real gap; calling it an integrity issue overstates the genre. Edit the cite; ignore the framing.

### "The review never walked the citation graph"

**Agree on the diagnosis, partial pushback on the framing.** A real walk takes hours and produces dozens of references. The brief specified ~3000–5000 words; the review is at ~4500. A graph walk that doubled the reference count would have exceeded the brief. The honest fix is to (a) acknowledge this scope choice in the Conclusion and (b) do a *budgeted* walk that picks up the most-cited follow-ons (which is the set the reviewer named).

### Anthropic alignment-auditing-agents post — already in zeitgeist, but cite

**Agree to cite, partial disagreement on "closest published industrial work."** The Anthropic post is closer than the review's prose admits, yes, but it is *also* an evolving research direction without a stable peer-reviewed publication. Cite as "Anthropic 2025 (research note)" rather than as a definitive industry baseline; some of its claims may shift.

---

## Edits checklist

Before any text changes land in `literature-review.md`:

1. Fix ImpossibleBench attribution: Wu → Zhong et al.
2. Source or remove the OpenHands SDK 72% figure.
3. Cut the "80% of technical lineage" claim from the Conclusion; replace with the concrete-coverage list.
4. Fix Sainz title capitalization in prose.
5. Drop "oral" qualifier on SWE-Bench unless sourceable.
6. Add Huang et al. 2023 to §4 with the artifact-generation framing from this response's opening.
7. Add Pan et al. 2024 to §4 with the context-separation framing.
8. Add Agentless and AutoCodeRover to §2 as the explicit counter-design.
9. Add AgentSpec, AgentAuditor, Anthropic 2025 alignment-auditing-agents to §5/§6.
10. Add TestPilot to §3.
11. Add EvalPlus (Liu et al.) to §1/§5.
12. Add METR 2025 reward-hacking report to §5.
13. Add Sapfix/Getafix/program-repair-in-CI body to §6.
14. Add SWE-Bench Multimodal mention to §1.
15. Complete Reflexion author list.
16. Flip §5's "closest peer" framing to the three-axes version.
17. Reframe §6/§7 from "thin" to "sparse but adjacent literatures exist."
18. Source all empirical claims listed in the table above.
19. Do a budgeted citation graph walk and note the budget in the Conclusion.
20. Fix the four readability failures (ACI, actor-critic, AST plagiarism, Inspect, verifier-guided).
21. Trim §1 paragraphs 1–2 and the Devin paragraph.
22. Expand §5 threat model, §6 priority-without-state, §3 Fuzz4All analogy.
23. Cut 42–50% duplicate from the Conclusion; add a compounding-regression callback.
24. Merge §6 and §7 into a single section.
25. Promote the integrity-audit threat model to a stand-alone subsection in §5.
26. Add the two suggested transitions (§4→§5, §5→§6).
27. Rewrite §1, §5, and Conclusion openings with hooks.
28. Add the benchmark-comparison table (§1).
29. Attempt the plan-placement diagram (Conclusion) and self-critique evolution (§4); defer to a separate file if ASCII doesn't work.
30. Acknowledge in the Conclusion the citation-graph-walk scope choice.

## Notes for Cycle 2

After applying these edits, Cycle 2 should expect:
- Citation accuracy will be much better; new findings should target newly-added claims, not the ones just fixed.
- §5 will have a different framing for the integrity audit; the reviewer should pressure-test whether the three-axes framing actually holds or is its own form of overstatement.
- The Huang/Pan additions will introduce new prose about "external grounding"; Cycle 2 should challenge whether the plan's loops actually have the external grounding claimed (e.g., does the QA scenario quality supervisor *really* have context separation, or does it share enough context with the scenario that Pan et al.'s findings still apply?).
- The merged §6/§7 section will be a new structural choice; Cycle 2 should test whether the merge is honest or just papering over the original split's weaknesses.
