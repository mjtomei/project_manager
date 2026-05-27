# Radar — Project-Scoped Multi-Platform Recommender + Two Reusable Agent Patterns

(news aggregator you can talk to, replacing social media's exploratory benefit at higher quality, scoped to a single project's context)

## Two problems this plan solves (the deeper motivation)

Two issues recur across every multi-agent surface pm has built or plans to build. Naming them up front because the radar is this plan's tangible deliverable, but the *patterns* the radar pioneers are what the plan really contributes.

### Problem 1 — Memory and attention

An agent's context window is too small to hold every relevant prior artifact, and summarizing loses fidelity that compounds over iterations. Today every agent in pm reaches for a different patch — stuffing more into context, RAG-style retrieval, summary notes — each with its own brittleness.

**Pattern this plan introduces:** **agent-as-user navigation.** Give agents the same navigation surface the human has — first-class links between every artifact (PRs, plans, notes, threads, items, comments, captures), helpers to open and read selectively, a path logger that records what each agent opened during a task. Agents then **walk a graph the same way the user does** instead of being handed a flat blob. This is the pattern pm already uses internally (grep, read, follow imports) and that Claude Code uses to navigate codebases — generalize it as a primitive for every agent surface, not something each one reinvents.

### Problem 2 — Prompt and behavior control

Changing how an agent behaves shouldn't require code edits. Users — and agents themselves — should be able to steer the system via natural language and direct file edits, both auditable.

**Pattern this plan introduces:** **first-class editable artifacts + chat-translates-to-edits.** Every prompt, source, strategy, and schedule the recommender uses is its own file in `pm/radar/`, readable and writable by both the user and the agents. A top-level **preferences chat** translates plain-English steering ("more depth on agent frameworks") into structured edits at the appropriate layer (add a site-scoped strategy entry, raise its schedule frequency, append a note to that topic's prompt). Generalizes the dynamic-mutation pattern from `pr-ff9b728` (plan auto-start watcher mutating plan files) to any pm-managed configuration surface.

### Why both patterns belong in this plan, not their own

Each pattern needs a real first user to shake out the seams. The radar exercises both heavily: navigation across threads / items / comments / linked PRs / linked plans / session transcripts, and behavioral control of which sources to read, when, with which prompts. Building the patterns inside this plan keeps them grounded; later plans pick them up as established primitives.

## The goal (one line)

A pm-internal recommender that replaces the *exploratory* benefit of social media — surfacing what's new across configurable sources, including content related to but not directly applicable to pm, with a chat-driven interface where the user and agents converse about discoveries, ideas get distilled into threads, and threads inspire features or updates — backed by the two reusable agent patterns above.

## Goal boundary — what this is and isn't

- **Is:** open-ended discovery + threaded discussion + project-aware filtering + summaries at multiple granularities + a way for discussions to seed PRs.
- **Is not:** a notification firehose, a competitor to social media for *connection* (it solves the *exploration* part, not the social part), a generic news aggregator (pm-scoped relevance is the moat), or a closed-loop "auto-adopt" system (the agent recommends; the human decides).
- **Goal voice of the recommender:** opinionated. The agent writes the opening of a conversation, not a neutral summary. Provocative framings, contrarian takes, tension with existing pm decisions, feature seeds — all in scope. Neutral summaries don't generate discussion; opinionated ones do.

## Architecture overview

Three layers, intentionally thin:

1. **Sourcing.** A small set of search **strategies** the agent picks per run — generic keyword search, site-scoped search, recent-feed crawl (no query — just "what's at the top of HN / this subreddit / this account today"), **vocabulary discovery** (meta-search: what does this community call X this year? — persists better keywords back into the topic files), **exploratory probe** (agent hypothesizes a source where interesting content might live and goes to look). All strategies are individual editable files; the agent rotates between them based on what each topic needs. Rate-limiting and source-shape are the agent's problem per call, not framework concerns.

2. **Triage and discussion.** Each candidate gets routed by the agent to an existing thread (or a proposed new one), evaluated against the topic and against project-relevance, and gets an **opening comment** written in conversation-starting voice. Comments accumulate. The agent can propose tag mutations (rename / split / merge / new tag). The user joins the conversation by replying directly in the thread file.

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
| `inspirational-value` | Just info | Sparks concrete idea(s) for pm or a thread |
| `architectural-fit` | Fights pm's patterns | Natural fit with pm's existing primitives |
| `adoption-cost` (inverted: high = good) | Expensive to integrate / adopt | Trivially cheap to integrate / adopt |
| `plan-alignment` | Unrelated to any open plan or PR | Directly relevant to an open plan or in-flight PR |

`architectural-fit`, `adoption-cost`, `plan-alignment` are the pm-flavored ones — they drive most of the `pm` topic's score and are weighted near zero on other topics by default. The full set is emitted on every item regardless, so the data is there if a user re-weights later.

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

- Thread storage at `pm/radar/threads/<slug>.md` — one file per thread, plain markdown with structured section headers per item.
- Item shape: `## item-<slug>-<n>` heading, frontmatter block with `source_url`, `tags`, `relevances`, `created_at`. Body is the item's content (snippet + source link).
- `relevances` is a mapping of tag → `{metrics: {<metric>: 1..10, ...}, composite: 0..1}` where `metrics` carries every metric from the active `metrics.yaml` set and `composite` is the weighted result (weighting is per-topic, defined in `metrics.yaml`). `pm` is always present as a built-in tag with its own weighting.
- `pm/radar/metrics.yaml` defines the metric set and per-topic weights. Editable by both the user and the preferences-chat agent. Schema validated.
- Comment shape: appended as `### YYYY-MM-DD HH:MM — <agent|matt>` subsections under an item.
- Tag namespace: free-form, the union of all tags ever used across items. A small `pm/radar/tags.yaml` tracks active tags + history of renames/merges/splits for permalink stability.
- Multi-factor relevance: emitted by the triage agent, stored on each item, read by the UI's two sliders.
- All references in item bodies / comments use the `[[...]]` link syntax from the navigation-primitive PR.

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

The agent that processes raw candidates into thread items:

- For each candidate: navigate (via the navigation primitive) the existing threads + relevant project state (open plans, in-flight PRs, recent merged work) to build context selectively.
- Decide: assign to an existing thread, or propose a new one (with proposed slug + one-line description).
- Write the **opening comment** in conversation-starting voice — opinionated, asks a question, surfaces tension with existing pm decisions, proposes a feature seed.
- Emit tags + per-tag relevance scores including `pm`. Scores are emitted as **per-metric 1–10 ratings** for the full active `metrics.yaml` set on every (item, tag) pair; the composite is computed from those + the per-topic weighting at evaluation time and stored alongside. The agent's prompt enumerates each metric with its 1/10 anchor definitions so ratings are calibrated, not free-form.
- Optionally propose tag mutations (rename / split / merge) when the agent notices the namespace getting sloppy.
- Optionally propose metric-set or weighting edits when the agent notices a pattern the existing metrics can't capture — surfaces as a suggested edit to `metrics.yaml` via the editable-artifacts primitive, not auto-applied.

Tests: a fake candidate goes through triage end-to-end and lands as a well-formed item with a non-trivial opening comment.

Depends on: data-model PR; navigation primitive PR.

### PR: Summary agent

Periodic and on-demand digests across all threads, at multiple time granularities (Today / This week / This month / This quarter — emitted only when activity warrants, so quiet weeks don't get an empty Today). Each digest is a short markdown document with inline `[[...]]` links into the items it references. Written to `pm/radar/summaries/<granularity>-<timestamp>.md`.

The summary surface in the UI reads these files. Scheduled trigger via the same schedule.yaml; on-demand trigger via `pm radar summarize [granularity]`.

Tests: round-trip generation; link integrity (every `[[...]]` resolves).

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

## Notes / philosophy

- **Project-scoped relevance is the moat.** Generic tech-radars exist; what makes this one different is reading every candidate against pm's specific open plans, in-flight PRs, prior decisions, and the persistent ledger of past triages. The radar's quality grows as the ledger grows.
- **Two relevance dimensions matter.** Project-relevance for the "is this actionable for pm?" cut; topic-relevance for the "is this interesting for its own sake?" cut. The sliders let the user pick which mode they're in — focused or exploratory. Replacing social media's *exploratory* benefit means the exploratory mode has to work, not just the focused mode.
- **The agent writes opening moves, not summaries.** Discussion-generation is the primary KPI; feature-seeding is secondary. Neutral surveys don't get replies; opinionated takes do. The evaluation prompt should orient the agent accordingly.
- **Walking, not stuffing.** Every agent in the radar (triage, summary, preferences, session-linker) uses the navigation primitive to read selectively from threads / items / comments / linked PRs / linked plans / transcripts. The result is each agent staying focused on its task with a small working context, while the totality of pm's history remains reachable.
- **The two patterns are the lasting contribution.** If the radar itself ends up being something we use lightly, the navigation primitive and the editable-artifacts primitive both still pay off across every other agent surface in pm — sign-off, review, QA, watchers, future plans. That's why they're Track A even though they're technically infrastructure for Track B's user-facing system.
