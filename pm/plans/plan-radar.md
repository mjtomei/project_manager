# Radar — Project-Scoped Multi-Platform Recommender + Two Reusable Agent Patterns

(news aggregator you can talk to, replacing social media's exploratory benefit at higher quality, scoped to a single project's context)

## The primary motivation: a structural improvement over mainstream recommendation systems

Mainstream recommendation systems — social feeds, news aggregators — operate without rich context about *who* the user is or *what they care about right now*. Lacking that context, they fall back on opaque engagement proxies (clicks, dwell time, reshares) and inevitably converge on a small set of failure modes: content that appeals to our more base instincts, content that foments disagreement because disagreement drives engagement, content optimized for the lowest common denominator of human attention. The pathology is structural — it's what happens when you do recommendation without per-user context, and replace context with proxies that work by averaging across users instead of by being shaped by a particular user's actual situation. The defining failure of these systems is **lack of personalization**: they are forced to optimize for the average user because they cannot accurately model any specific one, and the engagement proxies are the substitute they reach for in personalization's absence.

**Project-context-aware content servicing** — the radar's design — achieves much higher relevance precisely because it doesn't fall back on those opaque measures. Every candidate is read against this specific project's open plans, in-flight PRs, prior decisions, stated goals, and the persistent ledger of past triages. The triage agent is required to produce an auditable report — per-metric ratings, per-tag composites, an opinionated opening comment, and a structured feature-ideation step naming what pm could do in response. Two structural wins follow:

- **Interpretability.** Every relevance score breaks down to its per-metric ratings and the feature-ideation that grounded them. The user can audit *why* a recommendation surfaced and reject the agent's reasoning when it is off. Mainstream systems can't offer this because their relevance is the output of an opaque function over implicit user representations.
- **Auditability against known failure modes.** Because the report is structured, it can be mechanically checked for the specific pathologies of engagement-optimized systems — *is this surfacing because it would inflame me? because it appeals to a base instinct? because the agent confused engagement for value?* Those checks are tractable given the structured output; they are inexpressible in an engagement-optimized system whose relevance scoring has no auditable internal structure.

The pattern generalizes beyond pm: **mainstream recommenders are forced to target the lowest common denominator because they cannot personalize; more intelligent personalized recommenders — with rich per-user context and auditable structured reasoning — are not.** The radar is one instance; the design (project-aware + interpretable + auditable) is a durable contribution to the broader recommendation-system landscape.

## Two engineering problems that genuine personalization forces

Building a genuinely personalized recommender — one with the rich per-user context mainstream systems lack — forces two engineering problems. Both are problems specifically *with personalization of systems*, not generic multi-agent problems that happen to appear alongside the recommender. The radar gives each its first concrete deliverable, and the **patterns it pioneers in solving them** are reusable by every other agent surface in pm that needs to be personalized to a specific project or user.

### Problem 1 — Memory and attention (the personalization-context problem)

Personalization requires reading every candidate against the entirety of the user's relevant context — their open work, prior decisions, stated goals, accumulated history. An agent's context window is too small to hold every relevant prior artifact at once, and summarizing loses fidelity that compounds over iterations. Today every agent in pm reaches for a different patch — stuffing more into context, RAG-style retrieval, summary notes — each with its own brittleness; the radar makes this problem unavoidable rather than hideable because real personalization requires rich, current, structured access to the project's state.

**Pattern this plan introduces:** **agent-as-user navigation.** Give agents the same navigation surface the human has — first-class links between every artifact (PRs, plans, notes, threads, items, comments, captures), helpers to open and read selectively, a path logger that records what each agent opened during a task. Agents then **walk a graph the same way the user does** instead of being handed a flat blob. This is the pattern pm already uses internally (grep, read, follow imports) and that Claude Code uses to navigate codebases — generalize it as a primitive for every agent surface that needs personalization, not something each one reinvents.

### Problem 2 — Prompt and behavior control (the personalization-steering problem)

Personalization also requires the user to be able to steer the system to their preferences — in plain language, at any time, without code edits. A system whose prompts, sources, strategies, and schedules are hardcoded cannot be personalized at all; it can only be configured by a developer. Users — and agents themselves on the user's behalf — must be able to adjust the system's behavior via natural language and direct file edits, both auditable.

**Pattern this plan introduces:** **first-class editable artifacts + chat-translates-to-edits.** Every prompt, source, strategy, and schedule the recommender uses is its own file in `pm/radar/`, readable and writable by both the user and the agents. A top-level **preferences chat** translates plain-English steering ("more depth on agent frameworks") into structured edits at the appropriate layer (add a site-scoped strategy entry, raise its schedule frequency, append a note to that topic's prompt). Generalizes the dynamic-mutation pattern from `pr-ff9b728` (plan auto-start watcher mutating plan files) to any pm-managed configuration surface — and is the engineering substrate that makes natural-language personalization possible at all.

### Why building these patterns inside this plan is the right move

Each pattern needs a real first user to shake out the seams, and the recommender forces both heavily — navigation across threads / items / comments / linked PRs / linked plans / session transcripts, behavioral control of which sources to read with which prompts on what schedule. Both are unavoidable in any genuinely personalized system; the radar just happens to be the first surface where pm needs to solve them concretely. Building the patterns inside this plan keeps them grounded in a real use case; later plans pick them up as established primitives for whatever personalized surfaces they need.

## The goal (one line)

A pm-internal recommender that replaces the *exploratory* benefit of social media — surfacing what's new across configurable sources, including content related to but not directly applicable to pm, with a chat-driven interface where the user and agents converse about discoveries, ideas get distilled into threads, and threads inspire features or updates — backed by the two reusable agent patterns above.

## Goal boundary — what this is and isn't

- **Is:** open-ended discovery + threaded discussion + project-aware filtering + summaries at multiple granularities + a way for discussions to seed PRs.
- **Is not:** a notification firehose, a competitor to social media for *connection* (it solves the *exploration* part, not the social part), a generic news aggregator (pm-scoped relevance is the moat), or a closed-loop "auto-adopt" system (the agent recommends; the human decides).
- **Goal voice of the recommender:** opinionated. The agent writes the opening of a conversation, not a neutral summary. Provocative framings, contrarian takes, tension with existing pm decisions, feature seeds — all in scope. Neutral summaries don't generate discussion; opinionated ones do.

## Architecture overview

Three layers, intentionally thin:

1. **Sourcing.** A small set of search **strategies** the agent picks per run — generic keyword search, site-scoped search, recent-feed crawl (no query — just "what's at the top of HN / this subreddit / this account today"), **vocabulary discovery** (meta-search: what does this community call X this year? — persists better keywords back into the topic files), **exploratory probe** (agent hypothesizes a source where interesting content might live and goes to look). All strategies are individual editable files; the agent rotates between them based on what each topic needs. Rate-limiting and source-shape are the agent's problem per call, not framework concerns.

2. **Triage and discussion.** Each candidate is processed by the triage agent in a fixed order — **build context → feature ideation → opening comment → relevance scoring → structured mutation block at the end** — so topic decisions and tag mutations are informed by the just-completed analysis rather than snap judgment at item ingest. Items can carry **multiple tags**, each with its own composite score. The opening comment is written in conversation-starting voice. The agent can propose tag mutations (rename / split / merge / new tag), and crucially can also propose **retroactive re-tagging** — scanning existing items via the navigation primitive and adding a newly-relevant tag to historical items where it applies (so the namespace can evolve without leaving past items behind). Comments accumulate; the user joins the conversation by replying directly in the thread file.

3. **Interface.** A single chronological feed of items, with topic-keyword chips to filter, **two relevance sliders** (per-topic, project-general — pm is always a topic with its own score), summary panels at multiple time granularities (Today / This week / This month / This quarter — granularities chosen by activity, not fixed), and a top-of-page chat surface for preferences that translates to file edits. Static HTML (like #226's dashboard) for v1; TUI later.

### Relevance is a composite of explainable metrics

Each relevance score is **not a single opaque number** the agent emits. It is a composite of a small named set of **1–10 metrics** the agent scores individually, with a per-topic weighting that produces the final composite. The metric set and weights are themselves editable artifacts (`pm/radar/metrics.yaml`) — same editable-artifacts pattern as everything else.

This buys three things:

- **Explainability.** Hovering an item in the UI shows the metric breakdown — "0.62 because novelty=8, depth=4, project-fit=5, adoption-cost=3 (inverted: 7), plan-alignment=2." A reader instantly sees *why* something is high or low, not just *that* it is.
- **Steerability.** "I care less about novelty this month and more about depth" is a one-line edit to `metrics.yaml`'s weights via the preferences chat. No re-evaluation needed; existing items just recompose under the new weights.
- **Per-topic weighting.** Different topics legitimately want different weights — `agent-frameworks` weights architectural-fit and adoption-cost heavily; `language-model-research` weights depth + novelty, lightly weights adoption-cost. Same metric set, different lens per topic. The `pm` topic just has its own weighting like any other.

v1 metric set (starting point — fully editable):

| Metric | What 1 means | What 10 means |
|---|---|---|
| `novelty` | Old hat; we've seen many like it | Genuinely new direction in the field |
| `depth` | Press release / surface mention | Substantive technical content |
| `adjacency` | Tangential to the topic | Core to the topic |
| `direction-influence` | Feature-ideation produced no viable pm candidates | Feature-ideation produced multiple candidate features for pm whose alignment-to-stated-goals scores cluster ≥7/10 — the article is the kind of work most likely to influence pm's direction |
| `architectural-fit` | Fights pm's patterns | Natural fit with pm's existing primitives |
| `adoption-cost` (inverted: high = good) | Expensive to integrate / adopt | Trivially cheap to integrate / adopt |
| `plan-alignment` | Unrelated to any open plan or PR | Directly relevant to an open plan or in-flight PR |

`architectural-fit`, `adoption-cost`, `plan-alignment`, and `direction-influence` are the pm-flavored ones — they drive most of the `pm` topic's score and are weighted near zero on other topics by default. The full set is emitted on every item regardless, so the data is there if a user re-weights later. `direction-influence` is **grounded in the feature-ideation step** the triage agent performs (see the triage-agent PR below) rather than free-form intuition; it is the metric most closely tied to "how important is it for us to be aware of this work."

## Data model — Threads, Items, Comments, Tags, Relevances

Threads are a **new top-level pm entity** alongside Notes and Plans — not bound to any PR or plan. Each Thread is a markdown file at `pm/radar/threads/<slug>.md`. Items are entries within a thread; comments are sub-entries on items. Tags are a free namespace; an item carries zero-or-more tags including the built-in `pm` tag. Relevance scores are emitted per (item, tag) by the triage agent — including the (item, `pm`) score that drives project-relevance filtering.

This is a deliberate small entity-model addition rather than free-text fields, per the type-hygiene discipline from `plan-quality` — getting it right up front means every agent that touches threads (triage, summary, preferences-chat, session-linker, future plans' agents) consumes the same shape.

## v1 / MVP — minimum useful slice

Four PRs land the smallest version that produces value:

1. Data model — Threads + Items + Comments + Tags + multi-factor relevance scores.
2. Sources + schedule + strategies framework + a thin v1 strategy set (keyword search + recent-feed crawl).
3. Triage and evaluation agent — takes a candidate, finds the right thread, writes the opening comment, assigns tags + relevance scores.
4. News-aggregator HTML page — single feed, topic chips, two relevance sliders, summary panel (Today only for v1).

Everything below is post-MVP richness. MVP doesn't require the navigation primitive or the editable-artifacts primitive to be *generalized* — v1 can hand-roll those bits and the foundational PRs come along to lift them into pm-wide primitives once the radar has exercised them.

---

## Track A — Foundational agent patterns (reusable beyond the radar)

### PR: Agent-as-user navigation primitive

Generalize the radar's "agent follows links" mechanism into a pm-wide primitive every agent can use:

- A canonical reference syntax for cross-artifact links — `[[pr-XXX]]`, `[[plan-quality]]`, `[[thread:agent-frameworks]]`, `[[note-XYZ]]`, `[[capture:<pr_id>/scenarios/3/recording.cast]]`. Mirrors the wikilink syntax pm's own MEMORY frontmatter already uses.
- A small `pm_core/links.py` resolver that turns those references into paths an agent can `Read`. Cheap, no special infrastructure.
- A path logger that records what each agent opened during a task — per-task `~/.pm/agent-walks/<task-id>.json`. Two payoffs: (a) inspectable "why did the agent decide this?" trails, (b) frequently-walked paths become signal for what to surface in UIs.
- A **navigation hygiene** check (lands as an addendum in `plan-quality` Track A's review-prompt addendum, not a new PR): when an agent writes any artifact mentioning another, the mention SHOULD be a `[[...]]` link, not free text.

No new entity, no new storage — just a reference convention + a resolver + a logger. Reusable across sign-off agents, review agents, QA workers, watchers — anywhere an agent currently reads a stuffed-context blob, it can navigate selectively instead.

Plan: this plan. Lands early so subsequent PRs use it.

### PR: Editable artifacts + chat-translates-to-edits primitive

Generalize the dynamic-mutation pattern from `pr-ff9b728` (plan auto-start watcher mutating plan files) into a reusable surface for *any* user-and-agent-editable configuration in pm:

- A small framework where any directory of artifacts (`pm/radar/`, `pm/plans/`, `pm/watchers/`, etc.) can be declared **editable by both the user and a designated agent**.
- A **chat surface helper** an agent can host: takes a plain-English instruction from the user, identifies which file(s) the instruction is about, proposes an edit, logs the conversation alongside the edit. The user reviews and accepts (or the agent commits directly when the surface is configured for that — same gated/autonomous distinction as `plan-regression`).
- All edits commit with structured commit messages naming the source instruction. Fully audit-trailed.

The radar's preferences chat is the first user; later plans (e.g. watcher rules, future agent-configurable surfaces) pick it up as a primitive. Same shape, no per-surface reinvention.

Plan: this plan. Lands early; the radar's preferences-chat PR builds on it.

---

## Track B — Radar core (the user-facing system)

### PR: Thread + Item + Comment + Tag namespace + multi-factor relevance (data model)

- Thread storage at `pm/radar/threads/<slug>.md` — one file per thread, plain markdown with a top-of-file description block + structured section headers per item.
- Item shape: `## item-<slug>-<n>` heading, frontmatter block with `source_url`, `source_kind`, `authors`, `publication_date`, `tags` (list — multi-tag supported and expected), `relevances` (per-tag), `proposed_features` (see below), `discussed_in` (populated by the session-transcript linker), `created_at`. Body is the item's content (snippet + source link). All references in item bodies / comments use the `[[...]]` link syntax from the navigation-primitive PR.
- `relevances` is a mapping of tag → `{metrics: {<metric>: 1..10, ...}, composite: 0..1}` where `metrics` carries every metric from the active `metrics.yaml` set and `composite` is the weighted result (weighting is per-topic, defined in `metrics.yaml`). `pm` is always present as a built-in tag with its own weighting. Items can carry an arbitrary number of tags; each tag's composite is independent.
- `proposed_features` is a list of `{name, target, approach, goal_alignment_score: 1..10}` records produced by the triage agent's feature-ideation step (see triage PR). The aggregate (count × per-feature alignment) is the structured input grounding the `direction-influence` metric on the item's relevances.
- `pm/radar/metrics.yaml` defines the metric set and per-topic weights. Editable by both the user and the preferences-chat agent. Schema validated.
- Comment shape: appended as `### YYYY-MM-DD HH:MM — <agent|matt>` subsections under an item. The triage agent's structured mutation block is itself a recognized comment subtype (`agent-mutation-proposal`) so the editable-artifacts primitive can route proposals (topic-create, tag-rename, tag-merge, **retroactive-retag**, metric-edit, feature-handoff) to the right edit surface.
- Tag namespace: free-form, the union of all tags ever used across items. A small `pm/radar/tags.yaml` tracks active tags + a history of renames / merges / splits / retroactive-retags for permalink stability and audit. Retroactive re-tagging is a first-class operation — when a new tag is created later, a triage agent (or the user) can apply it to existing items where it applies.

Tests: round-trip read/write of a thread file; tag rename preserves permalinks; relevance-score parsing + range validation.

Plan: this plan. MVP item.

### PR: Sources + schedule + strategies framework + v1 strategy set

- `pm/radar/sources.yaml` — list of sources with per-source metadata (kind, hints for the agent).
- `pm/radar/schedule.yaml` — when each strategy runs against which topics.
- `pm/radar/strategies/<name>.md` — one file per strategy, each carrying its own prompt and parameters. v1 ships with:
  - `keyword-search.md` — generic web search; agent picks queries.
  - `recent-feed.md` — no query, just "what's recent here?" against a configured set of feeds / front pages.
- A small runner `pm radar run` that loads the schedule, picks strategies due, dispatches them to the agent, collects raw candidate lists, hands them off to the triage agent.

Tests: schedule parsing; strategy file format; runner dispatches correctly under faked-out network.

Plan: this plan. MVP item.

### PR: Vocabulary discovery strategy

Add `pm/radar/strategies/vocabulary-discovery.md`: meta-search whose output is not items but **better future keywords** — what do practitioners in a topic actually call the thing this year? Persists discovered vocabulary back into the relevant topic-prompt file so subsequent keyword/site searches use the right terms.

Highest-leverage of the search strategies because every successful discovery compounds — every future search benefits. Other strategies are stable in effectiveness; this one improves over time.

Tests: a vocab-discovery run on a fixture topic appends to the topic file with the discovered terms; subsequent keyword search reads them.

Depends on: sources/schedule/strategies framework PR.

### PR: Exploratory probe strategy

Add `pm/radar/strategies/exploratory-probe.md`: agent hypothesizes a source where interesting content for a topic might live ("a tools-channel in some Discord, a tag on hf.co/papers, a vendor changelog page"), goes and looks. Sometimes empty, sometimes finds a vein the keyword/recent-feed strategies wouldn't.

Different shape than the other strategies: input isn't a query, it's a topic; output is items plus *a discovered source* to consider adding to `sources.yaml` (proposed, not auto-added).

Tests: a probe run logs its hypothesized source + its findings; a found-source candidate becomes a suggested edit to `sources.yaml` via the editable-artifacts primitive.

Depends on: sources/schedule/strategies framework PR; editable-artifacts primitive PR.

### PR: Triage + evaluation agent

The agent that processes raw candidates into thread items. **Fixed output order: analysis first, structured mutations last.** Topic and tag decisions are better informed by the just-completed analysis than by snap judgment at item ingest; the agent's response is structured to enforce that.

For each candidate, the agent runs the following steps in order:

1. **Build context.** Navigate (via the navigation primitive) the existing threads + relevant project state — open plans, in-flight PRs, recent merged work, the project's stated goals (`pm/plans/plan-66d430f.md` or its descendants) — to assemble selective context. Path-log per the navigation primitive.

2. **Feature ideation (new — performed BEFORE relevance scoring).** For each issue, opportunity, or insight the candidate surfaces, ask three questions: *what could pm target to address this? how could pm address it? how close are those solutions to pm's currently stated goals?* The candidates the agent generates are **not limited to brand-new features** — explicitly in scope: small **changes to existing features**, new **use cases for existing surfaces** ("we already have X; this article shows X could also be used for Y"), and **scope simplifications** of in-flight work. The output is a list of candidate proposals, each tagged with kind (`new-feature` / `existing-feature-change` / `new-use-case` / `scope-simplification`) and carrying a one-line **target** (what pm would change or apply), a one-line **approach** (how), and a 1–10 **alignment-with-stated-goals** score. Persisted to the item's `proposed_features` field. This step is what grounds the `direction-influence` metric in the next step — instead of intuiting "does this inspire ideas?" the agent has actually done the ideation and can count the yield × alignment across all four kinds of proposals.

3. **Write the opening comment** in conversation-starting voice — opinionated, asks a question, surfaces tension with existing pm decisions. The feature-ideation output is visible in the comment as a "what could we do about it?" section, not buried in metadata. This is the load-bearing content the human will react to.

4. **Score relevances**, per-tag, grounded in the feature-ideation output where applicable. Per-tag relevance is emitted as 1–10 ratings on the full active `metrics.yaml` set; `direction-influence` specifically is calibrated against the feature-ideation yield (number of viable candidates × alignment scores). The composite is computed from per-metric ratings + per-topic weighting and stored alongside.

5. **Structured mutation block at the END.** After the analysis and scoring, the agent emits a parseable structured block listing proposed actions. Recognized mutation types:
   - **Topic assignment** — one or more existing tags (multi-tag is supported and common; each tag carries its own composite), OR a new-topic proposal (slug + one-line description, **informed by the just-completed analysis** rather than guessed up front).
   - **Tag mutations** — rename / split / merge of existing tags when the agent notices the namespace getting sloppy.
   - **Retroactive re-tagging** — scan existing items via the navigation primitive; propose adding a newly-relevant tag (often one just created by this triage pass) to historical items where it applies. Later triage passes can also surface retroactive-retag candidates for tags introduced earlier.
   - **Metric mutations** — proposed `metrics.yaml` edits when the agent notices a pattern the existing metrics can't capture.
   - **Feature hand-off** — for each feature in `proposed_features` whose `goal_alignment_score` is high enough to warrant its own pm artifact, an explicit proposal to file a new PR / add a note to an existing PR / edit a plan, routed via the editable-artifacts primitive.

The mutations are proposals — the editable-artifacts primitive applies them (gated or autonomous per the surface's configuration).

Tests: a fake candidate goes through triage end-to-end and produces a well-formed item with (a) a non-trivial opening comment containing a feature-ideation section, (b) a `proposed_features` array with at least one entry, (c) per-tag relevance scores with `direction-influence` consistent with the feature-ideation yield, and (d) a structured mutation block at the end with at least topic assignment and one feature hand-off.

Depends on: data-model PR; navigation primitive PR; editable-artifacts primitive PR.

### PR: Summary agent

Periodic and on-demand digests across all threads, at multiple time granularities (Today / This week / This month / This quarter — emitted only when activity warrants, so quiet weeks don't get an empty Today). Each digest is a short markdown document with inline `[[...]]` links into the items it references. Written to `pm/radar/summaries/<granularity>-<timestamp>.md`.

Each summary also includes a **feature-recommendation synthesis** section that aggregates the `proposed_features` across all items in the window, clusters near-duplicates (so the same feature surfaced by three different items isn't triple-counted), surfaces the candidates with highest cumulative `alignment-with-stated-goals` and highest mention frequency, and presents them as a project-resource-allocation candidate list. Together with the per-item analyses, the synthesis turns the summary into a regular input to *"what should pm work on next?"* — a feed that runs from "what's happening in the field" all the way to "what we should consider doing about it." This is the substrate the forward-trajectory section below builds on for a genuinely self-guided project.

The summary surface in the UI reads these files. Scheduled trigger via the same schedule.yaml; on-demand trigger via `pm radar summarize [granularity]`.

Tests: round-trip generation; link integrity (every `[[...]]` resolves); feature-recommendation synthesis correctly aggregates and clusters `proposed_features` across a fixture set of items.

Depends on: data-model PR; navigation primitive PR.

### PR: Preferences chat

The top-of-page chat surface where the user steers the recommender in plain English. Translates instructions to edits via the editable-artifacts primitive — adjust a slider threshold, add a site to `sources.yaml`, change a strategy's prompt, raise a schedule frequency, add a tag to the watchlist. All edits are logged as a thread (`pm/radar/threads/preferences.md`) so the steering history is itself part of the radar.

Tests: a fixture instruction routes to the correct file edit; the edit commits with a structured message naming the source instruction.

Depends on: editable-artifacts primitive PR.

### PR: News-aggregator HTML page

The user-facing surface, static HTML (like #226's sign-off dashboard):

- **Single chronological feed** of items across all threads.
- **Topic-keyword chips** at the top (click to filter, multi-select).
- **Two relevance sliders** — per-topic (when a topic chip is active) and project-general (the `pm` tag's score). Both threshold against the **composite** score; hovering an item reveals the per-metric breakdown so the user can see *why* it scored where it did. A small "weights" affordance lets the user re-weight inline via the preferences chat without leaving the page.
- **Summary panel** above the feed showing the most recent digest at each available granularity.
- **Currently-running info pane** showing what the agent is doing right now (running strategy X over topic Y, evaluating item N).
- **Preferences chat** input at the top.

Reads from `pm/radar/` files directly. Co-located static export — open the file in a browser, no server. Client-side filtering for the chips + sliders (same shape as #226's dashboard).

Tests: page renders; chips filter correctly; sliders threshold correctly; summary panel links resolve.

Depends on: data-model PR; summary agent PR; preferences chat PR; navigation primitive PR.

### PR: Session-transcript linker

A separate agent that runs on a cadence (or `pm radar link-sessions` on demand) reading recent Claude session transcripts and inserting links from threads/items to **specific transcript locations** where a thread or topic was discussed. Output: each item gains a `discussed_in:` frontmatter list of transcript-location references.

Two payoffs:
- The thread becomes a hub: from any thread you can jump to the actual conversations that produced or referenced it.
- The link graph becomes **queryable in the navigation primitive's path-log direction** — "find every transcript that referenced this topic" / "find every thread referenced from this PR's review session."

How links get generated: the linker agent reads transcripts via the navigation primitive (so it doesn't have to load them all into context), scans for thread/topic mentions, attaches anchored references. Same pattern as the rest of the radar — the agent navigates and selectively extracts, doesn't summarize.

Tests: a fixture session transcript that mentions a fixture thread results in a `discussed_in:` entry on the right item; the link resolves back to the transcript anchor.

Depends on: data-model PR; navigation primitive PR.

### PR: TUI surface (later)

Mirror of the HTML page in the TUI — same data, same filtering, same sliders. Lower priority than the HTML page since the HTML works for the exploratory-reading mode and the TUI's strength is keyboard-driven workflow that's less critical here.

Depends on: data-model PR; news-aggregator HTML page PR (data shape established there).

---

## Cross-pollination with other plans

- **`plan-litreview` (`plan-3119574`)** — same shape (ingest + score against project state + surface), different content (academic papers vs. ecosystem chatter). Ingest infrastructure should be shared; ideally the strategies-framework PR here can be the version litreview also uses. Possibly merges with this plan's sourcing PR once both are fleshed out.
- **`plan-quality` Track B's "external seeding"** — that's the *one-shot* version of this plan (when the health-check audit runs, search the web for similar projects + best practices to seed refactor proposals). The radar is the **always-on daemon version**; the audit reads from the radar's persisted ledger instead of doing its own ad-hoc searches. Less duplicated network IO, richer prior context for the audit.
- **`plan-self-improve`** — improvement of pm by competing against itself; the radar feeds it the outside-the-self component (what's the rest of the field doing).
- **`pr-ff9b728`** (plan auto-start watcher mutating plan files) — the editable-artifacts primitive in this plan is the generalized version of what that PR does for plans. Likely worth a follow-on note on `pr-ff9b728` to migrate it onto the generalized primitive once it lands here.

## Depends on

- The two primitives (navigation + editable-artifacts) are MVP-internal; the rest of Track B builds on them.
- No external blocking dependencies. Self-contained; can land in parallel with the rest of pm's work.

## Status counts

- pending: 0 (none filed yet; `pm plan load plan-radar` after approval)
- in_progress: 0
- merged: 0

## Forward trajectory: where this leads

The MVP delivers a personalized recommender for one user / one project. Several capabilities follow naturally once the core lands; they are sketched here as orientation rather than committed scope, but they shape the design choices the MVP makes (the persistent decision ledger, the structured `proposed_features` shape, the navigation primitive's path logs, the editable-artifacts substrate — all designed to be reusable for what follows).

**Self-guided project resource allocation.** Once the summary agent's feature-recommendation synthesis is running, the radar produces — every week or month — a ranked list of features the field's recent work suggests pm should consider, clustered and weighted by alignment to stated goals. Combined with pm's existing internal signals (open plans, in-flight PRs, bug discovery), the synthesis becomes a real input to *"what should pm work on next?"*. A subsequent plan could close the loop entirely: the synthesis feeds a watcher that proposes plan edits or PR additions, the user approves or rejects, and the project's resource allocation begins to be guided by convergent signals from the field. A genuinely **self-guided project** — reviewing what others are doing, identifying the patterns most relevant to its own goals, and acting on them — becomes possible once that loop closes.

**Cross-plan feature collaboration (depends on hierarchical plans, `plan-cb4ef69`).** Once hierarchical plans land, the radar can detect candidate features that recur across multiple plans within a single pm project — and propose, **speculatively and dynamically**, breaking them out into their own shared dependency, possibly into their own project. The proposal is reversible: the agent surfaces the candidate, the user decides, the artifact moves, and the cross-references update. This is the project-internal version of the cross-collaboration pattern; the social-features version (below) is the same pattern across users.

**Cross-USER collaboration is its own plan: [[plan-collaboration]].** The vision continues outward — automated collaboration between users, projects, and organizations; shadow pm projects for non-pm parties; on-ramp via demos of existing pm machinery (radar, bug-finding, sign-off). That track is substantial on its own and has its own thesis (open + intelligent-collaboration-capable outcompetes closed) and its own structural requirements (public-facing visibility, permissions, trust / safety). It is split out so this plan stays focused on the personalized-recommender substrate; this plan's MVP is what `plan-collaboration` builds on.

Even within this plan's scope, the two within-project visions above (self-guided resource allocation + cross-plan dependency extraction) compound: a self-guided project becomes more interesting when it can speculatively spin off shared dependencies. The MVP doesn't need either; it needs to leave room for both.

## Notes / philosophy

- **Project-scoped relevance is the moat.** Generic tech-radars exist; what makes this one different is reading every candidate against pm's specific open plans, in-flight PRs, prior decisions, and the persistent ledger of past triages. The radar's quality grows as the ledger grows.
- **Two relevance dimensions matter.** Project-relevance for the "is this actionable for pm?" cut; topic-relevance for the "is this interesting for its own sake?" cut. The sliders let the user pick which mode they're in — focused or exploratory. Replacing social media's *exploratory* benefit means the exploratory mode has to work, not just the focused mode.
- **The agent writes opening moves, not summaries.** Discussion-generation is the primary KPI; feature-seeding is secondary. Neutral surveys don't get replies; opinionated takes do. The evaluation prompt should orient the agent accordingly.
- **Walking, not stuffing.** Every agent in the radar (triage, summary, preferences, session-linker) uses the navigation primitive to read selectively from threads / items / comments / linked PRs / linked plans / transcripts. The result is each agent staying focused on its task with a small working context, while the totality of pm's history remains reachable.
- **The two patterns are the lasting contribution.** If the radar itself ends up being something we use lightly, the navigation primitive and the editable-artifacts primitive both still pay off across every other agent surface in pm — sign-off, review, QA, watchers, future plans. That's why they're Track A even though they're technically infrastructure for Track B's user-facing system.
