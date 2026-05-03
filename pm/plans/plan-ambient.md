# Ambient interface — context-aware multi-surface UX

## Vision

Move toward a computer interface that, in the limit, reads your mind. The path is to give Claude as much context as possible about what the user is currently doing, looking at, and likely to want next — and to disambiguate natural-language requests against that context rather than against the bare words alone.

The unifying premise: every "surface" the user sees is also a sensor. Whatever Claude renders to a screen, Claude can also know is being shown, where the user's attention sits within it, and how it relates to other surfaces the user has open. Natural-language interaction becomes resolvable against a rich runtime model of what the user is doing, not a guess from words.

## Surfaces and signals

A surface is any independent display Claude can render to and read from: a webapp viewer, a touch panel, a TUI pane, a phone screen showing documentation, etc. Surfaces are explicitly multi-device and multi-modal — one user can have several at once on different physical screens.

Signals Claude should be able to query, per surface and across surfaces:

- **What is open** — which surfaces are currently active, what document/page/view each one is showing, and at what version.
- **What is in focus** — within each active surface, the visible portion (viewport range, scroll position, selected element). Reported by the surface back to the host, not predicted.
- **What is being attended to** — recent activity per surface: gaze (when available), touch and scroll events, viewport changes, selection changes, focus changes. **Every signal is retained as history, not just current value** — a time-series per signal — so Claude can reason about *how* the user arrived where they are, not only where they happen to be at this instant. **Histories are persistent, not ephemeral.** The full archive lives on disk indefinitely; in-memory ring buffers exist only as a cache for cheap recent-past queries. Long-tail queries hit the archive directly.
- **Time since last interaction** — both per-surface (when did the user last touch/scroll/look at this surface?) and globally (when did the user last do anything anywhere?). Long idle gaps lower confidence in deictic resolution — "this" is much weaker after 15 minutes of silence than after 15 seconds.
- **Cross-surface relations** — when the user says "this," which surface does "this" most plausibly refer to? Most-recent-attention wins; ties break on most-recent-edit; everything is gated by global idleness.

Together these become a single ambient-context query Claude makes before responding to anything ambiguous: "what is the user actually looking at right now, across all their devices?" — and, because histories persist, "what has the user habitually attended to, across weeks and months, that should inform the prior?"

## Storage tier and persistence

All signals — display state, attention state, signal histories — persist to disk indefinitely. The system is designed for long-horizon archives (years, terabytes) rather than ephemeral last-N-minutes buffers. This is a deliberate choice: a multi-year archive of attention is qualitatively different from a 10-minute window — it lets the agent learn priors (what the user typically reads on Tuesday mornings, which sections of which docs they historically dwell on) rather than only resolve the current turn.

Implications for design:

- **In-memory ring buffers are a cache, not the truth.** Recent-past queries (last few minutes) hit memory; older queries hit the archive.
- **Storage shape needs to be picked early.** Per-surface JSON files are fine for live registry state but not for a time-series archive. The archive uses one shared store keyed by `(surface_id, signal_name, timestamp)` — SQLite per host is the v1 default, with the schema designed so it can swap to a remote time-series database later without protocol changes.
- **No automatic expiry by default.** Retention is set explicitly (per-host, per-signal-class) when the user wants it, not as a default behavior. The default is "keep everything."

## Privacy and consent

A persistent archive of attention is a meaningfully different artifact from an ephemeral one. The plan adopts these principles upfront, even where implementation is deferred:

- **All attention history is the user's data.** Nothing leaves the host without an explicit, scoped action by the user.
- **Exportability.** The full archive can be exported to a portable format (e.g. a zip of OTel-shaped JSONL) at any time.
- **Scoped deletion.** The user can delete history by surface, by signal class, by time range, or wholesale. Deletion is real (rows removed), not soft-flagged.
- **Per-signal opt-in for high-sensitivity classes.** Gaze, camera-derived signals, and any future biometric signals are off by default and require an explicit opt-in per surface, with a visible indicator on the surface itself when active.
- **Inspection.** A `pm history inspect` view lets the user see what is currently being recorded for any surface — never invisible.

These are principles for the plan to track; the concrete implementation is its own PR (see Phase 2).

## Related work and prior art — what to import, what we're missing

Each entry leads with what we should take from this work or where it points to a gap in the current plan. Background is one-line; the rest is action-oriented.

**Ubiquitous computing / calm technology** (Weiser, Brown — Xerox PARC, late 80s–90s; Active Badge, PARCTab). [The Computer for the 21st Century (Weiser, 1991)](https://calmtech.com/papers/computer-for-the-21st-century) · [Ubiquitous computing — Wikipedia](https://en.wikipedia.org/wiki/Ubiquitous_computing) · [Weiser's vision and legacy (Sam Kinsley)](https://www.samkinsley.com/2010/03/12/ubiquitous-computing-mark-weisers-vision-and-legacy/).
- *Import:* the calm-tech principles — surfaces inform without demanding focus, the user never has to ask what state the system is in.
- *Likely missing:* a *presence-without-attention* surface kind. Active Badge's lesson: low-bandwidth ambient indicators (someone is in the room, the build is green, the user is idle) deserve their own surface kind that never tries to grab focus. Consider adding it as a future surface alongside doc/browse/tts.
- *Difference:* Weiser's vision predated LLMs; he had to design context-aware *behaviors* by hand. We use a model that can read structured context and do disambiguation, so the substrate stays simple and most of the intelligence lives in the agent.

**Multimodal interaction and deictic reference resolution** (CHI/IUI/HRI literature, decades). [Gaze and Speech in Multimodal HCI: Scoping Review, CHI 2026](https://dl.acm.org/doi/10.1145/3772318.3791662) · [An Exploration of Eye Gaze in Spoken Language Processing, ACL 2007](https://aclanthology.org/N07-1036.pdf) · [Deixis, Meta-Perceptive Gaze Practices, and Joint Attention (Frontiers in Psychology, 2020)](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2020.01779/full) · [The Role of Gaze as a Deictic Cue in HRI](https://link.springer.com/chapter/10.1007/978-3-030-50439-7_32).
- *Import:* concrete fusion techniques for combining gaze + speech to resolve "this/that/here". Specifically the finding that gaze improves resolution most when domain knowledge is limited — applicable to our resolver when the user references something *outside* known surfaces.
- *Likely missing:* dialogue-history integration in the resolver. Our `pm context resolve` currently looks at attention state alone; the literature shows recent conversation context is often a stronger signal than gaze. Worth threading prior turns into resolution — possible enhancement to the attention-ranking PR.
- *Likely missing:* an evaluation harness. The literature has standard accuracy metrics for reference resolution. We should have a small benchmark suite by the time the resolver PR lands.
- *Difference:* most prior systems assume one screen; we explicitly handle multi-device with a global context query.

**Activity recognition platform APIs** ([Google Activity Recognition](https://developers.google.com/location-context/activity-recognition) · [Microsoft Graph userActivity](https://learn.microsoft.com/en-us/graph/api/resources/projectrome-activity?view=graph-rest-1.0) · [Android Transition API](https://developer.android.com/guide/topics/location/transitions)).
- *Import:* the (type, confidence, timestamp) shape for events and the lifecycle model (start/active/end). Microsoft's userActivity in particular maps an *activity* to an array of *history items* with start_time/active_duration — a cleaner shape than raw event lists.
- *Likely missing:* explicit **confidence scores** on every signal. Today's plan emits raw events; we should attach a confidence per event (gaze tracker confidence, dwell-vs-pause distinction, scroll-stop intentionality), so the resolver can weight uncertain signals less. Add to the protocol PR.
- *Likely missing:* **transition events** as first-class. Right now we have viewport/selection state changes; we don't explicitly model "user just entered region X" / "left region Y" as transitions. The Android Transition API's lesson: transitions are easier to reason over than continuous state. Add `transitions` as an event family in `SignalHistories`.
- *Difference:* platform APIs target physical-world activity (walking, in-vehicle); ours target on-screen attention.

**User interaction traces as time series** ([Alan Dix, HCI'92](https://alandix.com/academic/papers/hci92-goms/)).
- *Import:* validates the history-everywhere decision.
- *Likely missing:* **motif / pattern recognition** over histories. Trace-mining shows recurring sub-sequences ("user always checks the goals section before accepting changes in the spec section") are predictively useful. Future PR: detect repeating motifs in attention histories and surface them in `pm context` as priors.
- *Difference:* Dix's framing is for offline analysis of traces; we want the same shape consumed live by an agent.

**Attention-aware AI and LLM grounding**. [Towards Attention-Aware LLMs (arXiv 2511.06468)](https://arxiv.org/html/2511.06468v1) · [ContextAgent (arXiv 2505.14668)](https://arxiv.org/html/2505.14668v1) · [Eye-Tracking and Biometric Feedback in UX Research (arXiv 2505.21982)](https://arxiv.org/pdf/2505.21982).
- *Import:* ContextAgent's pattern of extracting multi-dimensional contexts from sensory perception and feeding them to a *proactive* agent loop (not just on-demand). The protocol's `pm context` is currently pull-only; ContextAgent suggests a push channel too.
- *Likely missing:* a **proactive context-change trigger**. When ambient context shifts in a way that's likely material (the user just opened a new surface, the document jumped to a new section, idle suddenly ends after 10 minutes), Claude should be notifiable rather than having to poll. Future PR: an SSE-style stream of *context-level* events analogous to per-surface events.
- *Likely missing:* a **cognitive-load / attention-quality signal** at the user level. The literature reports significant gains in cognitive-load prediction by combining eye-tracking with physiological/behavioral signals; saccade-entropy from our implicit-signals PR is a weak proxy. Could extend with typing cadence, scroll velocity variance, dwell variance. Fold into the implicit-signals PR or as a successor.
- *Difference:* most prior work focuses on a single sensor stream feeding a single agent on a single device. We're explicitly multi-surface and multi-device, with the agent querying an aggregated context rather than sensing directly.

**GUI grounding for agents**. [MobileFlow (arXiv 2407.04346)](https://arxiv.org/html/2407.04346v3) · [Grounding Multimodal LLMs in Actions (Apple)](https://machinelearning.apple.com/research/grounding-multimodal-large) · [MP-GUI (CVPR 2025)](https://openaccess.thecvf.com/content/CVPR2025/papers/Wang_MP-GUI_Modality_Perception_with_MLLMs_for_GUI_Understanding_CVPR_2025_paper.pdf) · [Attention-driven GUI Grounding (arXiv 2412.10840)](https://arxiv.org/html/2412.10840) · [GUI Agents Paper List (OSU NLP)](https://github.com/OSU-NLP-Group/GUI-Agents-Paper-List/blob/main/paper_by_key/paper_grounding.md).
- *Import:* visual grounding handles surfaces we don't control. Our protocol only sees what we built (rc, browse, doc, tts). The user has lots of surfaces we *can't* instrument: arbitrary browser tabs, IDE, email, Slack, the OS itself.
- *Likely missing:* a **screen-capture gateway surface** that uses an MLLM to extract structured state from a screenshot of an external window/app and feeds it into the same protocol shape. This would widen the "what can the user be looking at" coverage substantially. Strong candidate for its own PR — possibly Phase 5.
- *Difference:* we control the surfaces, so we can expose structured state directly through the protocol — higher fidelity, lower cost. The two approaches compose: visual grounding for surfaces we don't control, structured protocol for surfaces we do.

**Multi-device / multi-surface UX architecture**. [Designing multi-user multi-device systems (MUM 2008)](https://dl.acm.org/doi/10.1145/1543137.1543140) · [Multi-User Tracking (MultiTrack, CHI 2019)](https://dl.acm.org/doi/10.1145/3290605.3300766).
- *Import:* the explicit info-space / interaction-space distinction (what is being shown vs how the user can act on it) and the idea of *annotated mappings* between them.
- *Likely missing:* **surface-routing recommendations**. The literature implies some information types are better-suited to some devices (mobile = glance, tablet = read, laptop = edit). Today Claude picks any registered surface to display things on; a future helper could recommend *which surface should display X* based on the user's active devices and the content type. Lightweight: a function `recommend_surface(content_kind, registered_surfaces)`.
- *Difference:* prior work mostly addresses how multiple humans share devices; we address one human spreading across multiple devices, with an LLM agent as a co-user.

**Calm-tech design constraints worth carrying forward**: surfaces should inform without demanding focus (no notifications-first design); the user should never have to *ask* the system what state it's in (state should be queryable on demand by the agent and visible by glance to the user); sensors and displays are unified, not separated.

## Open-source projects worth borrowing from

What to import from each, and where they expose gaps in the current plan.

**Yjs Awareness Protocol** ([docs](https://docs.yjs.dev/api/about-awareness), [repo](https://github.com/yjs/yjs)).
- *Import:* the awareness/document split (ephemeral JSON awareness CRDT separate from the persisted document CRDT), conventional-not-standardized field names, automatic clearing on disconnect, the idea that awareness is freely-extensible JSON. Model `AttentionState` and the SSE event stream on this directly.
- *Likely missing:* **multi-client awareness merging**. Yjs handles many clients reporting awareness simultaneously; our current plan has one user but multiple surfaces, and each surface's `/api/viewport` last-write-wins is a degenerate version of the same problem. If a single user has the same surface open on two devices, we should be merging awareness across clients, not overwriting. Worth thinking about now since it's a small generalization.
- *Likely missing:* **adopting Yjs itself for the document side** of the rc viewer. Today the rc server holds the doc in memory and accepts edits via /api/accept. If a future PR adds two viewers editing or a collaborative human, Yjs gives that for free.
- *Difference:* Yjs is built for many human peers; we have one human and one agent. We get to pick what to take and skip the parts that exist for many-peer convergence.

**Plan 9 acme** ([paper](https://plan9.io/sys/doc/acme/acme.html), [plan9port](https://9fans.github.io/plan9port/man/man1/acme.html)).
- *Import:* the per-window file-system interface as a protocol shape. The agent driving surfaces is exactly analogous to external programs driving acme through 9P. Per-surface paths (`/api/surface/<id>/display`, `/.../attention`, `/.../events`) mirror acme's `/acme/<id>/body`, `/tag`, `/event` and let the protocol scale to many surfaces without adding new top-level routes per surface.
- *Likely missing:* the **tag/body split** mapped onto our surfaces. acme's tag is the per-window command line; our surfaces today don't have a per-surface command channel. Adding one would let the user issue commands scoped to a specific surface ("on the doc viewer, jump to line 100") via voice without ambiguity.
- *Likely missing:* the **`/event` channel** — acme exposes user events (clicks, keystrokes, mouse moves) as a file an external program can read. Our protocol has `/api/events` for *output* but no symmetric input-event log. Adding one would directly satisfy the implicit-signals PR's requirements with a more uniform shape.
- *Difference:* acme uses 9P (file-system semantics) where we use REST + SSE. The shape rhymes; the wire format doesn't. We don't gain by switching but we should adopt acme's path discipline.

**Phoenix LiveView and Hotwire/Turbo Streams** ([LiveView](https://hexdocs.pm/phoenix_live_view/Phoenix.LiveView.html), [Turbo](https://hotwired.dev/)).
- *Import:* minimal-diff updates with version numbers, reconnect-and-resync via a stable view ID, partial-page streaming as the default rather than full re-renders. For the SSE stream, send field-level diffs against the last known version, not full state.
- *Likely missing:* a **liveness ping** over the SSE channel. LiveView heartbeats so it can detect a stalled connection from the *server* side, not only the client. Our SSE today is purely server→client push; if the client goes silent (page suspended), the server doesn't know. Adding an occasional client-pong gives us a real "is this surface alive" signal that the registry can use to expire dead clients without waiting for a TCP timeout.
- *Likely missing:* **temporary-state assigns** (LiveView's pattern of marking some assigns as flash/transient). Useful for "Claude just said X" or "user accepted the proposal 2s ago" — short-lived UI state that shouldn't stick around in the persistent display.
- *Difference:* LiveView is Elixir/BEAM and uses WebSockets; we're Python/FastAPI on SSE. We won't adopt LiveView itself, but the diff-with-version + heartbeat + transient-assigns patterns transfer cleanly.

**Liveblocks Presence API + tldraw** ([Liveblocks docs](https://liveblocks.io/docs), [tldraw cursors](https://tldraw.dev/sdk-features/cursors)).
- *Import:* the architectural posture of keeping the multiplayer/protocol layer cleanly isolated from surface implementations so backends can swap. Pin the surface protocol as the single seam at `pm_core/surfaces/protocol.py`; surface implementations import only from there.
- *Likely missing:* **smooth cursor interpolation** patterns (tldraw uses `perfect-cursors`). Once we have gaze and a remote viewer, raw gaze coordinates jitter; the user-visible "where Claude thinks I'm looking" indicator (if we add one for transparency) would benefit from interpolation rather than raw values.
- *Likely missing:* **a presence indicator on the viewer** showing "Claude is here, looking at lines 12–20." Liveblocks/tldraw show other users' cursors; we should consider showing Claude's *intended* attention back to the user, so the user has a visible thread to grab when Claude misjudges focus.
- *Difference:* Liveblocks is a hosted multiplayer service; we're self-hosted on a LAN. The patterns transfer; the infrastructure does not.

**WebGazer.js** ([webgazer.cs.brown.edu](https://webgazer.cs.brown.edu/), [GitHub](https://github.com/brownhci/WebGazer)).
- *Import:* directly as the gaze provider. Privacy framing (client-side only) and calibration (interaction-driven, no calibration ceremony) are both solved. The gaze PR ships as `gaze.js = WebGazer + thin /api/attention poster` — already updated.
- *Likely missing:* a **calibration-confidence display** on the surface. WebGazer's accuracy varies wildly with lighting, glasses, head movement; surfacing the current confidence to both user and Claude lets the resolver weight gaze accordingly and lets the user know when to recalibrate.
- *Difference:* WebGazer is purely a sensor; we'd ingest its output into our protocol. No architectural mismatch.

**PostHog session replay + OpenTelemetry** ([retention docs](https://posthog.com/docs/session-replay/recording-retention), [OTLP integration](https://posthog.com/docs/llm-analytics/installation/opentelemetry)).
- *Import:* OTLP-shaped event records (timestamp + name + attributes) for `SignalHistories`. PostHog's blob-storage tier shows that recordings can grow much larger than database-friendly sizes and benefit from a separate storage backend.
- *Likely missing:* **session-replay export**. We're already collecting time-series histories; with a small additional schema we could export them as OTel session traces and feed them into PostHog or any OTel-compatible backend for offline analysis. Useful for debugging "why did Claude resolve 'this' wrongly?" after the fact. Could be its own PR or a thin layer on the implicit-signals PR.
- *Likely missing:* **configurable retention per signal type**. PostHog lets retention be configured per recording category; today our protocol PR has flat per-signal retention. Per-signal-type configurability would let us keep gaze short (high volume) and selection-changes long (low volume, high value) without hand-tuning every surface.
- *Difference:* PostHog is a hosted analytics product; we want the data shape and retention model, not the service.

**Mosh** ([mosh.org](https://mosh.org/)).
- *Import:* the state-synchronization protocol idea — server holds canonical state, client predicts locally, both reconcile lazily. This is the well-tested answer to mobile-browser SSE staleness if our naive reconnect proves insufficient.
- *Likely missing:* **predicted local echo** in the rc webapp. After the user taps to scroll, we wait for the server's confirming /api/viewport response before showing it; mosh's predict-and-reconcile would let touch feel instant even on flaky LAN. Probably overkill for v1 but the right model if responsiveness becomes an issue.
- *Difference:* mosh is a terminal protocol; we'd be borrowing its conceptual model, not its code.

## Distinction from existing pm flows

- **TUI panes** are session-internal and assumed co-located with the host. Ambient surfaces are explicitly remote, multi-device, and read-back-capable.
- The ambient model treats every surface as both display and sensor by default. That symmetry is the point; it's what makes the disambiguation possible.

**Folded in from plan-ff4f1a7**: the `pm tts` work originally scoped under that plan is moved into this one as a TTS-as-surface PR (Phase 2). plan-ff4f1a7 had not implemented it; an ambient audio output surface is the more natural home, and folding it in lets it share the protocol, registry, and context model with the visual surfaces. plan-ff4f1a7's adversarial-review-and-question-queue work stays where it is — only the TTS piece moves. STT remains out of scope here (Claude Code's built-in `/voice` covers it).

## Goals

1. Establish a per-host service registry of active ambient surfaces — what is open, on what device, showing what.
2. Define a small, common surface protocol: each surface reports its viewport / selection / focus / attention back to the host through a uniform API, so Claude has one place to query context.
3. Build concrete surfaces against the protocol — starting with the document viewer, then expanding (project browser, doc reader, etc.).
4. Layer in attention signals as they become available: explicit (touch, scroll, click) first, implicit (gaze tracking) later.
5. Make ambient context queryable by any Claude session on the host so disambiguation works the same way regardless of which session the user is talking to.

## Direction

The first PR — the `pm rc` document viewer — establishes the surface pattern in miniature. Subsequent PRs generalize: extract the protocol, build a host-local registry, add more surfaces, and layer in cross-surface attention reasoning and gaze. We deliberately build the registry only after we have a second surface forcing the seam to be obvious.

## Phase 1 — Foundation (after pr-4702a11 lands)

### PR: Common surface protocol — extract from `pm rc`
`pr-39a4e66` (depends on: pr-4702a11)

Define the shape every ambient surface exposes, in `pm_core/surfaces/protocol.py`. Types: `SurfaceKind` enum, `SurfaceIdentity` (id, kind, host, lan_url, started_at), `DisplayState` (what is shown, version), `AttentionState` (viewport_top/bottom, selection, focus_target, last_user_input_at). Surfaces serve `GET /api/surface` returning all three. The rc viewer's `/api/doc` is refactored to use this shape (with a transitional alias). No new behavior — pure extraction so subsequent surfaces have a target to implement against. Depends on: pr-4702a11.

### PR: Persistent attention archive — SQLite time-series store
`pr-3fee106` (depends on: pr-39a4e66)

Per-host persistent archive for all surface signals. SQLite (one DB per host at `~/.pm/surfaces/archive.db`) with a single events table indexed by (surface_id, signal_name, timestamp_ns). Each surface implementation writes through a shared batched writer (`pm_core/surfaces/archive.py`) so per-event cost stays low. The protocol's in-memory SignalHistories becomes a cache populated from this archive on surface restart, not the source of truth. No expiry by default — retention is configurable but defaults to "keep everything." Read API supports cross-surface queries over arbitrary time ranges, so long-horizon queries ("where did the user dwell most last month?") work without paying the cost of holding everything in memory.

### PR: Privacy controls — export, delete, inspect, opt-in
`pr-7e19be4` (depends on: pr-39a4e66)

CLI commands implementing the plan's privacy principles: `pm history inspect` shows what is being recorded for each surface, `pm history export` produces a portable OTel-shaped JSONL zip, `pm history delete` does scoped real-row deletion, `pm history opt-in/opt-out` toggles high-sensitivity signal classes (gaze, camera, biometric — off by default). Surfaces with active high-sensitivity recording display a visible indicator.

### PR: Host-local surface registry
`pr-dc4f5fe` (depends on: pr-39a4e66)

File-backed registry at `~/.pm/surfaces/<id>.json` — each surface writes its descriptor (identity + URL + pid) on startup, removes on shutdown. Stale-entry cleanup on read when pid is gone. Library API in `pm_core/surfaces/registry.py`: `list_surfaces()`, `get_surface(id)`, `register(identity)`, `deregister(id)`. New CLI `pm surfaces list` (debug aid). The rc server is updated to register/deregister via this. Depends on: protocol PR.

## Phase 2 — More surfaces

### PR: Project browser surface
`pr-a0d778e` (depends on: pr-dc4f5fe)

New `pm browse start [--port N]` command (pm-session only). Webapp surface that renders the current pm project tree (plans → PRs → files) as a touch-navigable list. Claude drives selection and focus via the protocol; user can also tap to navigate. Read-only — tapping selects but does not mutate. Registers with the surface registry. Used during voice sessions for "show me the regression plan" / "open pr-3b2847c" style navigation. Depends on: protocol + registry.

### PR: TTS audio surface — `pm tts`
`pr-10fd776` (depends on: pr-dc4f5fe)

New `pm tts on` / `pm tts off` per-session toggle (folded in from plan-ff4f1a7, which had not yet implemented it). Two complementary modes both live behind the same surface kind:

- **Active push** (preferred where Claude can call it directly): a `pm tts say` CLI / API endpoint Claude invokes to speak specific text. Bypasses the noisy terminal-scraping path entirely.
- **Passive capture** (fallback for cases where Claude can't be modified to call the API): the original plan-ff4f1a7 design — a daemon that polls `tmux capture-pane` every ~200ms, strips ANSI, diffs against the prior snapshot, suppresses chrome / tool calls / code, and speaks new prose lines.

TTS implements the surface protocol: registers as kind=tts in the registry, exposes `GET /api/surface` returning identity + display (recent spoken-text history) + attention (currently-playing? user-interrupted? last-spoken-at?). TTS backend pluggable via env var — `say` (macOS) and `piper` (Linux, local) by default; no cloud requirement. Per-session toggle is preserved. Latency target: speech begins within ~1s of a sentence becoming available.

Tests: active-push API speaks given text; passive-capture daemon detects new prose lines and speaks them; chrome/tool-call/code suppression in passive mode; surface registration; GET /api/surface returns recent spoken-text history; per-session toggle behavior; backend selection via env var. Depends on: protocol + registry.

### PR: Doc reader surface
`pr-101fae8` (depends on: pr-dc4f5fe)

New `pm doc start <path> [--port N]` command (pm-session only). Like rc but read-only and Claude-only-driven. For reference material: codebase files, generated docs, screenshots Claude wants to point the user at. No selection/proposal/accept — just display, focus, and viewport reporting. Implements the protocol; registers with the registry. Depends on: protocol + registry.

## Phase 3 — Context queryability

### PR: Active-surface context query
`pr-dce4cbb` (depends on: pr-a0d778e, pr-101fae8)

New `pm context` CLI. Reads the surface registry, queries each active surface's `/api/surface`, returns a JSON summary: per-surface identity + display + attention. Available to any Claude session on the host — the disambiguation primitive. Output is stable JSON so prompts can include it directly or selectively. Depends on: registry + at least one extra surface from Phase 2 (so the API is exercised against more than one surface kind).

### PR: Cross-surface attention ranking
`pr-7b6ae74` (depends on: pr-dce4cbb)

Augment `pm context` with a ranked "most-recent-attention" list across all active surfaces (combining `last_user_input_at` and a touch-recency weight). Add `pm context resolve "<phrase>"` that takes a natural-language pointer ("this paragraph", "the second one") and returns the most-likely referent surface + region — or returns ambiguity metadata when multiple are within tolerance, so Claude can ask. Tests cover the two-surface tie case and the recency-decay case. Depends on: active-surface context query.

## Phase 4 — Richer attention

### PR: Gaze tracking — protocol extension and browser provider
`pr-8c21624` (depends on: pr-39a4e66)

Extend `AttentionState` with optional `gaze: {x, y, region_id, last_at}`. Add a JS provider (`pm_core/surfaces/static/gaze.js`) using an in-browser library (e.g. WebGazer) that computes gaze coordinates and posts to `/api/attention`. Surfaces opt in by including the provider script. The context query exposes gaze when present, omits when not. Surfaces without gaze keep working — purely additive. Depends on: protocol PR.

### PR: Implicit attention signals — dwell, saccade, scroll-stop
`pr-34421be` (depends on: pr-8c21624, pr-7b6ae74)

Track dwell time per region, saccade entropy as an "attention quality" score, scroll-stop events as a fallback when no gaze data is available. Surface these in `pm context` as soft weights. The `pm context resolve` command uses them to break ties more confidently. Depends on: gaze PR (uses gaze when present, falls back to scroll/touch otherwise).

## Cross-reference

plan-ff4f1a7 covers adversarial review of plans/specs and the question queue. Its TTS section has been folded into this plan (above). plan-ff4f1a7's references to `/rc` as the mobile-reach mechanism are satisfied by `pr-4702a11` here.

## PRs already landed/registered

### PR: `pm rc` mobile voice document viewer and editor
`pr-4702a11`

First concrete ambient surface — establishes the surface pattern (server on host, browser on remote device, Claude drives via API, surface reports viewport back) and the cross-device assumption (voice client and viewer are independent surfaces). See PR description for full API and architecture.
