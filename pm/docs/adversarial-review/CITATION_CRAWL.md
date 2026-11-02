# Citation Crawl and Key-Phrase Search (methodology)

Sub-methodology for the citation audit (`CITATION_USE_AUDIT.md`) and for the older by-hand citation-graph walk in `METHODOLOGY.md` step 5. The job: surface candidate citations — academic via Scholar walks, non-academic via key-phrase search — when an audit needs to find what *should* be cited but isn't, or when a reviewer is walking from a named seed.

## Citation crawl (academic)

For each relevant paper, walk both directions on Google Scholar (and on arXiv where applicable).

### Forward — "cited by"

- Open the paper's Scholar entry; click "Cited by N."
- Sort by date (most recent first) to catch work that postdates the artifact's bibliography.
- Default depth: **1** (papers that directly cite the seed). Depth 2 (papers citing papers that cite the seed) only for the most load-bearing seeds where the crawl is expected to surface adjacent prior art the artifact urgently needs.
- Filter: keep papers whose title or abstract suggests methodological or topical proximity to the artifact. Drop noise (unrelated applied uses, off-domain citations) with one-line rationale.

### Backward — references

- Read the seed paper's reference list.
- Mark papers that the seed treats as load-bearing — cited multiple times, or cited in the methodology / results / related-work-discussion sections — and any whose title is novel to the candidate set.

### Output

Per seed, per direction: a list of (title, authors, year, link, brief note on why it surfaced). These go into the next iteration's Phase 1 candidate set.

## Key-phrase derivation and search (non-academic)

Academic citation crawls miss blog posts, lab notes, GitHub repos, vendor research pages, and OpenReview workshop submissions. Key-phrase search catches them — and key phrases are also how iteration 1 of a from-scratch flow gets its seed candidates.

### Derive key phrases

From the seed paper's abstract and conclusion (or from the artifact text directly, for iteration-1 seeding), extract **3–5 short phrases** that characterize the specific contribution. Prefer phrases the source itself coins or emphasizes, not generic terms.

Examples:
- From Cheng et al. 2026: "verbalized assumptions," "user-intent dimensions," "objectivity-seeking probe."
- From DeepConf: "deep think with confidence," "low-confidence trace filtering."
- From a from-scratch artifact on "sycophancy as entropy-greedy mirroring": "entropy-greedy decoding," "ventriloquized perspectives," "between-perspective entropy."

The phrases must be specific enough to filter — "language models" is too broad; "RLHF" alone is too broad; "RLHF-induced sycophancy preference" is specific.

### Search

Run each key phrase against:

- **Google** (web search), date-filtered to the last 12 or 24 months as appropriate to the topic's pace.
- **arXiv full-text search** (not just title).
- **transformer-circuits.pub**, **alignment.anthropic.com**, **transluce.org**, **openai.com/research**, **deepmind.google/research** — lab pages that frequently publish before or instead of arXiv.
- **lesswrong.com / alignment forum** — where alignment-relevant arguments sometimes land before publication.
- **GitHub** — for tool releases, eval harnesses, dataset repos.
- **OpenReview** — for workshop submissions and rejected-but-discoverable work.

Surface anything that uses the phrase and bears on the artifact's argument.

### Output

Per seed: a list of non-academic sources surfaced, with link + 1-sentence note on why it's relevant. These go into the next iteration's Phase 1 candidate set, where they receive the same scan treatment as academic candidates.

## Depth control

The crawl depth is configurable per seed:

- **depth-0** — no crawl. Use only when a seed is excluded from further crawling for known-stale reasons (e.g., a foundational reference that's already been crawled in a prior iteration and would produce identical results).
- **depth-1 (default)** — direct citations only (cited-by + references). Sufficient for most relevant seeds.
- **depth-2** — citations-of-citations. Use sparingly, only for the most load-bearing seeds.

Document the depth applied per seed in the crawl output. Depth is part of the audit trail — a later reviewer needs to know whether absence of a candidate means "not surfaced" or "not searched at this depth."

## Iteration-1 seeding (from-scratch flows)

When the artifact has no existing references, the iteration-1 candidate set is produced by:

1. Deriving key phrases from the artifact text itself (the topic, research question, or draft prose).
2. Running the key-phrase search across academic + non-academic sources.
3. Treating the surfaced papers as the iteration-1 candidate set for Phase 1.

This is the same key-phrase machinery as the per-seed crawl, just applied to the artifact instead of to a seed paper.

## Convergence

The crawl drives the flow's iteration loop. Convergence is signalled when a full iteration's crawls surface zero new candidates that subsequently reach the *relevant* threshold in Phase 1.

A long tail of *not relevant* surfacings is normal — the crawl finds many adjacent works that the relevance criterion filters out, and that filtering is itself part of the audit trail. Convergence is *zero new relevant*, not zero new candidates.

## Output file naming

Save crawl outputs to `pm/docs/adversarial-review/CRAWL_<artifact>_iter<N>.md`, with one section per seed paper. Iteration `N`'s crawl produces iteration `N+1`'s candidate set for Phase 1.

## Coverage reporting

Every crawl output ends with a **Coverage** section listing, per seed: which directions were walked, the date range covered, the count of new citing/cited papers surfaced, and the depth applied. If the walk found nothing new, say so — that is a positive convergence signal in the same shape as a verbosity pass finding nothing to cut, and the dashboard reads it accordingly.

The coverage section is the audit trail for *what was searched* — a later reviewer who finds a key paper that should have been surfaced can check whether the missing paper was *not searched* (gap in the seed list or depth) versus *searched and dropped* (filter decision the reviewer disagrees with).

## Search recipes — by topic cluster

Concrete, named tactics ported from earlier adversarial-review-loop experience (`METHODOLOGY.md` step 5f). Where a relevant work falls into one of these clusters, the recipe is the starting recipe for its crawl. Add new recipes here as new topic clusters emerge in new artifacts.

- **Activation-to-language readout / probing methodology.** Search transformer-circuits.pub, alignment.anthropic.com, transluce.org, and OpenReview for "activation verbalizer," "activation oracle," "patchscope," "latent decoder." Run a Scholar *cited-by* walk on Patchscopes (Ghandeharioun 2024).
- **Autonomous coding agents / benchmarks.** Search swebench.com, OpenHands' GitHub, and Scholar *cited-by* on SWE-Bench (Jimenez 2024). Check the SWE-Bench Verified leaderboard for recent submissions whose papers haven't yet hit arXiv.
- **LLM agent integrity / cheating detection.** Search nist.gov/caisi, alignment.anthropic.com, and Scholar *cited-by* on ImpossibleBench (Zhong 2025).
- **Social-psychology framework for person perception.** Search Scholar *cited-by* on Fiske/Cuddy SCM (2002) and Goodwin 2014 — both have substantial follow-up literature including the dispute over how many dimensions structure person perception.

The recipes are starting points, not exhaustive. The expectation: extract the recipe's first 20–30 hits, scan their titles + abstracts, escalate the topically-proximate ones into the next iteration's Phase 1 candidate set.

## Recovery from "this citation doesn't exist"

When a Phase 2 review or a Phase 5 reviewer flags a citation as unverifiable or hallucinated, the *next* search step must explicitly check Google Scholar, the lab's own page, and OpenReview for the named work before treating it as not-found. The Omerta-era loop produced the worked example: Cycle 1's reviewer flagged "Choi et al. 2025" and the response substituted a different paper — but Choi/Transluce 2025 was real, just not on arXiv. Default to *search more places* before *doesn't exist*.
