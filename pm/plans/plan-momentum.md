# Momentum — Credible Next-Step Direction

(developer **attention** is pm's scarce resource once throughput is solved; this plan maintains a live, leverage-ranked list of the most interesting next steps — mined from chat logs and development effort — and surfaces them, plus revivable and related work, **credibly**, where the user already looks)

> Thin plan by design: mostly **thesis + engine + integration**. It *reuses* [[plan-radar]]'s relevance/surfacing machinery and [[plan-memory]]'s sifting-over-own-history, *lands its surface* in `pm guide`'s assist prompt and the TUI home window, and *complements* [[plan-pulse]] (energy-fit re-ranking) and [[plan-ambient]] (timing/placement). **Buildable now with heuristics + a prompted overseer — no model training** — so it fits the "finish the mind+sensorium refactor first" constraint.

## Thesis

The founding thesis says the multiplier lives in the orchestration + auto-QA layer. Once that layer makes *generation* cheap and parallel, the binding constraint moves: **the scarce resource becomes the developer's attention.** With many parallel streams, PRs, plans, and parked threads, the human can't track what matters; the highest-leverage next step is constantly being lost to noise, forgetting, or stall. So **credible mechanisms for directing developer attention are themselves a core multiplier** — the post-throughput bottleneck.

"**Credible**" is the whole game. An attention mechanism is trivial to build and trivial to ruin: surface by recency/flash/volume and the user learns to ignore it after the first cry-wolf. The mechanism's entire value is that *when pm surfaces a next step, it's right.* That makes this the **first human-facing surface that needs grounded-usefulness from day one** — the engagement carve-out that is fine for radar's general feed ([[plan-radar]]) is *disqualified here*.

## Design principles (load-bearing)

1. **Credibility is the objective; engagement is disqualified.** Rank by *grounded leverage to project momentum*, never by recency, chat-volume, or clicks. One mis-surfaced item costs trust the mechanism runs on. This is the human-facing instance of the grounded-usefulness price signal.
2. **Legible and earned, not noisy** (radar's discipline). Surface sparingly, always with a one-line *why* and *how to act*. Silence is the default; a surfaced item is a claim that earns or spends trust.
3. **The items are the project's own action-graph** — PRs, plans, stalled threads, chat-derived TODOs, parked decisions. Not external content (that's [[plan-radar]]) and not energy-matched task selection (that's [[plan-pulse]]).
4. **Reuse, don't rebuild.** Relevance composite + surfacing from radar; session-transcript sifting + recall-over-own-history from memory; the surface from `pm guide`. This plan owns the *thesis, the engine, and the integration*, nothing else.
5. **No model training in v1.** Heuristics + a *prompted* holistic overseer (rung 1). The learned grounded ranker is deferred and shares [[plan-memory]]'s deferred grounded gate.
6. **Surface where attention already is.** Integrate with `pm guide`, the home window, and (later) ambient placement — calm-tech: inform without demanding focus. Don't invent a new screen that competes for attention.
7. **Close a grounded feedback loop.** Did surfacing an item lead to *progress* (a commit, a revived thread, a resolved question) — not merely to a view? Signed, grounded, logged. Calibrates sparseness and ranking, without re-importing the engagement trap.

## What "leverage" means (the ranking objective)

A next step's leverage is **grounded value × momentum**, estimated from named, explainable factors (reuse radar's 1–10 explainable composite), then re-scored by the prompted overseer for credibility:

- **Finish-line proximity** — nearly-done work; finishing has the highest ROI per remaining unit.
- **Newly-unblocked** — a dependency just landed; previously-impossible work is now doable.
- **Revivable-stalled** — dormant but promising (no activity in N days, but it had real momentum / excitement / a near-miss); a small nudge restarts it.
- **Precondition-met** — work that was explicitly *parked pending X*, where X has now happened (e.g., "revisit the capstone after core-loop progress" — the mechanism should resurface that when the progress lands).
- **Relevance-to-current-focus** — adjacency to what the user is touching now (this is where [[plan-ambient]]'s attention signals time/place the surfacing).
- **Alignment-with-stated-goals** — the work advances a declared plan/goal (reuse radar's `alignment` metric).

Anti-factors (push *down*, not up): raw chat-volume, recency-alone, flashiness — the things attention rewards and credibility punishes.

## Signals (where the candidates come from)

- **Development effort** (cheapest, v1): PR/plan state from `project.yaml`, git activity, review/QA status, dependency edges. Yields finish-line, unblocked, stalled, and contested candidates with no NLP.
- **Chat logs** (richer, v1.5): session transcripts mined (reuse [[plan-memory]]'s session-transcript sifting) for open questions, decisions, surfaced TODOs, and **parked items** ("come back to this later", "let's defer X") with their stated precondition. This is the human-facing cousin of [[plan-memory]]'s involuntary recall — same machinery, *human* target instead of agent.
- **Ambient** (optional): [[plan-ambient]]'s attention/focus signals for *when* and *where* to surface, not *what*.

## Architecture overview

```
project.yaml + git + review/QA state ─┐
session transcripts (memory sifting) ─┼─► candidate NextSteps (kind, target, why, source-refs)
parked-item / precondition extraction ┘
        candidates ──► leverage composite (reuse radar) ──► prompted credibility overseer ──► ranked, deduped, decaying Momentum list
        top-k ──► surfaced in `pm guide` assist prompt + home window (legible, earned, sparse, with why + how-to-act)
        later ──► did it lead to progress? (grounded, signed) ──► calibrate sparseness + ranking
```

## Data model

`NextStep` (persisted, like radar items): `id`, `kind` (`finish` / `unblock` / `revive` / `precondition-met` / `related` / `new`), `target` (one line), `why` (one line, the surfaced explanation), `how_to_act` (the concrete first move / TUI key), `leverage` (explainable composite), `source_refs` (chat-log slices, PR/plan ids, git refs), `last_surfaced`, `outcome` (grounded: ignored / surfaced-not-acted / acted / led-to-progress).

## v1 / MVP — minimum useful slice

- **One signal**: development effort (PR/plan/git state) — no chat mining yet.
- **Ranker**: leverage composite + a *prompted* overseer for credibility (no learning).
- **Surface**: upgrade `pm guide`'s `build_assist_prompt()` from a static lifecycle walk to a **leverage-ranked next-steps list with why + how-to-act**.
- **Feedback**: `outcome` logged (grounded), surfaced for inspection; no learning yet.

This makes `pm guide` immediately more useful and proves the credibility discipline before adding chat-log mining and home-window surfacing.

## Implementation PR sequence

### PR: `NextStep` model + dev-effort signal extractor + leverage composite (reuse radar)
Extract finish/unblock/stalled/contested candidates from `project.yaml` + git + review/QA state; score with the explainable composite.

### PR: prompted credibility overseer + ranked, deduped, decaying Momentum list
The holistic re-scorer (grounded, not engagement); maintain the live list.

### PR: surface in `pm guide` assist prompt (the help prompt)
Upgrade `build_assist_prompt()` to render the top-k with `why` + `how_to_act`. The primary, immediate win.

### PR: chat-log mining signal (parked items, open questions, TODOs)
Reuse [[plan-memory]]'s session-transcript sifting; extract parked items + their preconditions.

### PR: TUI home-window Momentum surface (legible, earned, sparse)
A low-bandwidth, never-grabbing surface (calm-tech), one or two items, dismissible.

### PR: grounded feedback loop + calibration
`outcome` → did surfacing lead to progress; calibrate sparseness and ranking (no model training — heuristic calibration).

### PR: revival + precondition-met detector
Detect dormant-but-promising work and parked items whose stated precondition has now been met; resurface them (the parked-capstone case).

## Depends on

- **[[plan-radar]]** — the explainable relevance composite, the legible-not-noisy surfacing discipline, the feature-ideation pattern, the periodic-agent pattern.
- **[[plan-memory]]** — session-transcript sifting and recall-over-own-history (this plan is its human-facing cousin); shares the **deferred grounded-usefulness gate** for the eventual learned ranker.
- **[[plan-sensorium]]** — `Artifact`/`PmCommand` reads for PR/plan state; git/review/QA state.
- **[[plan-pulse]]** (complement) — can re-rank the Momentum list by developer energy/flow fit.
- **[[plan-ambient]]** (complement) — attention/focus signals for surfacing *timing and placement*.
- **`pm guide` (`guide.py`)** — `build_assist_prompt()` is the primary surface; `needs_guide()` the trigger.

## Cross-references

- The **prompted overseer** here is the **first human-facing instance of the grounded-usefulness work** (`pm/docs/principle-coverage-audit.md` addendum) — the bridge between the deferred learned gate and a near-term human-facing payoff.
- The eventual learned ranker is the same "external small model over text, per-project, grounded labels" pattern; deferred with [[plan-memory]]'s gate.

## Open questions

- **The leverage objective** — operationalizing "interesting / high-leverage" is the grounded price-signal problem, human-facing. v1 uses heuristic factors + a prompted overseer; the learned version is deferred.
- **Calibration / sparseness** — how often to surface before the mechanism becomes noise. Start very sparse; let the grounded feedback loosen it.
- **Precondition detection** — recognizing that a parked item's stated precondition ("after core-loop progress") has been met is itself a judgment; v1 keyword/heuristic, judged by the overseer.
- **The engagement trap in the feedback loop** — "acted-on" is closer to grounded than "viewed," but only "led-to-progress" is truly grounded; keep the loop anchored on outcome.

## Status counts

- pending: 0 (none filed; plan is draft)
- in_progress: 0
- merged: 0

## Forward trajectory

The prompted overseer → a **learned, per-project grounded ranker** (external small model over the project's text, trained on the grounded `outcome` labels) — deferred, sharing [[plan-memory]]'s gate. Longer term, the Momentum engine is the human-facing readout of the same grounded-usefulness price signal that, at the capstone scale (`mind-search` — parked), becomes the economy's currency.

## Notes / philosophy

- **Attention is the post-throughput bottleneck.** Solving generation/QA throughput relocates the constraint to human steering; this plan is about spending that scarce resource well.
- **Credibility is spent, not given.** Every surfaced item is a claim; the mechanism lives or dies on being right, which is why engagement is disqualified here even though it's tolerated on radar's general feed.
- **Self-referential validation.** The clearest test of the mechanism: does it resurface *our own* parked threads (the capstone) at the right time? If it can't credibly manage this very conversation's backlog, it isn't working.
