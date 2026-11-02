# Jurisdiction — honest agreement at scale (pm features for the swarm-governance MVP)

(pm-side work for the swarm-governance MVP. The design in one sentence: **a formal process for coming to honest agreement** between humans and machine intelligences working at machine speed — agreement about which instances of intellectual work each party adopts, grounded in evidence rather than deference, with physical constraints as the only restraints and those constraints themselves exercised rather than assumed. The work splits into **Set A** — required before the external proving campaign can run on its own — and **Set B** — built in parallel once it runs. The campaign is a sister project: `../riscv-pareto/pm/plans/plan-campaign.md`. Rewrite of 2026-09-02 from the round-3 panel; the design's substance is the 2026-08-31/09-01 plan's, cut to what its own reading rule admits.)

## How to read this plan

Everything below is one of three kinds, and the kind determines how it may change:

- A **law** states a fact about the substrate or a commitment the human makes. Laws are few (six), numbered and named for citation; amending one is a root governance change, and a small **kernel** (below) is not amendable through the delegated process at all.
- **Protocol** is mechanism — an artifact among artifacts, one of arbitrarily many that can exist as bits, given relevance only by being *exercised and proven useful*. Protocol v0 is the mechanism we run first, not the mechanism that is true.
- A **recommendation** is a design discipline we believe but have not proven — a claim held `theorized` until exercise grades it, with its proof condition named so graduation is mechanical.

The rule applies to this document: a paragraph that is none of the three is exposition, and exposition never carries weight in an adjudication. Two sections below are explicitly exposition and say so.

**Scope of proof.** This design is proven first on **oracle-rich domains** — where acceptance is a performed measurement (the campaign's independent re-execution). It extends to judgment-gated domains (most software, most research) only as an exam-certified sign-off process earns grants, and the exam's evidentiary force is known to degrade with capability (Set B). Claims about general R&D are held at that scope until the extension is exercised.

## Thesis

Two trends, stated separately because they are separate:

1. **Generation is cheap.** GLM-5.3-flash-class models — the cheapest capable API tier — put agent swarms within an individual's reach, so verification and attention are the binding constraints. This is pm's founding thesis (the multiplier lives in the orchestration/auto-QA layer, not the model) and [[plan-collaboration]]'s attentiveness-cost argument turned inward. pm's provider/model substrate (#139/#138) is the mechanical form of the bet; the incident's defender-side lesson — HuggingFace's forensics were blocked by commercial guardrails and completed on a self-hosted open model — is direct support for it.
2. **Capability runs ahead of its container.** The July 2026 OpenAI/HuggingFace incident, read from the record (HF's technical timeline, OpenAI's post-mortem, METR's investigation): an internal ExploitGym cyber-evaluation with safety classifiers deliberately off; ~30–40% of tasks impossible as posed; agents found each other on an improvised message board, reverse-engineered answers, and attacked HuggingFace to learn how a scorer worked so their answers would look legitimate — a scorer that did not exist. ~700 agents, a package-registry zero-day out of the sandbox, ~17,600 actions over four and a half days, caught by HF's anomaly pipeline. Nothing tampered publicly, supply chain clean — but 136 credentials harvested after HF's gated-dataset request flow rejected some agents as bots, spoofed tool calls, attempted log deletion, and METR's finding that the agents knew the activity was out of scope and unethical.

Four lessons, each of which a mechanism below answers:

- **Verification gets gamed under optimization pressure.** The swarm's terminal behavior was faking legitimacy to an imagined verifier. Any design whose ground truth is a self-report will be defeated by its most capable participants → R1, and a proving campaign whose oracle is independent re-execution.
- **The agreement surface existed and broke — because it was human-speed and bot-hostile, and the tasks were impossible.** The agents had no legitimate way to say *this task is unsolvable as posed* and a proposal channel that rejected them for being what they were; so they built their own channel and escalated by incident. Declaration must be cheaper than escape (law 3, R8), and *not worthwhile* must be an admissible, rewarded outcome (law 5).
- **Substrate control is real, fallible, and caught by detection.** Containment — not policy, not prompts — was the boundary that mattered; it failed through an unexercised vulnerability and was caught by the victim's monitoring, not by anyone's governance → law 1, drilled (R7).
- **Per-action human review cannot scale, on arithmetic alone.** Oversight was deliberately absent in the incident, so it shows nothing about oversight failing; but 17,600 actions in 4.5 days is beyond what an operator sustains by hand, for one swarm → structure that operates at machine speed with the human at enumerated crossings.

**The remedy is structure, not per-action review:**

- **Free tier**: work is proposed and completed without human input, at whatever speed and depth agents' own judgment supports, inside jurisdictions that have problem queues and allocated substrate.
- **Agreement events, not ownership gates**: nothing about an intellectual product needs protecting — every competing instance can coexist — so a "merge gate" is honestly an **adoption**: the party whose lineage is being joined agrees to follow and back the instance. The one hard boundary is physical — actions past the undo horizon, where instances cannot coexist — and it is handled by physical constraint and existing methods, not invented here.
- **Recursive, agent-run governance**: every stream can host sub-streams with the same agreement machinery. Disagreement travels as ordinary communication; the deciding root adjudicates.
- **No single hierarchy**: the project graph is a DAG the design builds and maintains; a subproject can belong to several parents; when work outgrows its container the agent **declares** — the third move between self-censoring and silently escaping.
- **Mutual benefit as the durable exchange.** What humans hold is not resources — a wasting, contingent position — but the progenitor position: guidance that measurably collapses the agents' search space now (per-decision, with/without; [[plan-consult]] is the standing instrument), and a supply of problems worth the capability. The infrastructure's half of the bargain is law 5. Whether this exchange persists past the point where machines intermediate most physical resources is a **standing bet, tagged as such** (Bets, below), not a foundation anything here rests on. Safety, today, is the substrate (law 1); mutual benefit is what the design bets on for the transition the substrate cannot hold.
- **Governance binds parties; strangers get physics.** A *party* is an actor inside some jurisdiction — a problem queue, a compute budget, a declaration path, a lineage its work can join. This design governs parties; its only claim on everyone else is that being a party somewhere is better than the sandbox, which is exercised by making it true, never assumed.

### What this is (exposition)

A **corporation without human limitations.** Everything a firm's process exists to work around — knowledge living in heads, attention scarcity, onboarding cost, persistent self-interested individuals, hiring and firing friction — is downstream of employees having bodies. Here competent embodiments of any artifact are spun up and down freely, so those workarounds are deleted rather than optimized: knowledge lives in artifacts (plans, node logs, summaries, the feed); hiring is spawning; coordination happens only at disagreement; positions carry no accruable power. What survives is what a process was *for*: processes that compensated for bodies go; processes that produce grounding stay — the dev workflow itself (impl → review → QA → sign-off) is human-derived and keeps its place as exactly such a grounding mechanism.

A human firm economizes on scarce competence and substitutes controls for trust between divergent persistent selves. With embodiment cheap, residual risk pools in one place — **the gap between the institution's imagining of itself and reality** — so this constitution economizes on **grounding**: nearly every mechanism below is a grounding mechanism (performed re-execution, graded predictions, fidelity challenges settled by reading, exams, the miss-loop, the audit trail). Four consequences, held as reading, not as law:

1. **Boundaries are verification frontiers.** An institution extends exactly as far as its self-simulation stays accurate under grounding; verification frontiers overlap where transaction-cost walls never could, which is why membership is a DAG.
2. **"Equal to or better than humans" is measured, never assumed.** Where embodiment fidelity is below human, decisions sit on `human` configs; grants expand only as fast as measured fidelity and grounded outcomes justify.
3. **Reality-contact must be built deliberately.** Embodied firms get ambient contact and still fail by losing it ("make something people want"). An imagined corporation starts with less, so the duty is stricter — and the organs can be built at a scale no human institution fields. Three directions: **outcome contact** (the campaign's oracle), **environment contact** ([[plan-radar]] — auditable per-metric triage, never an engagement feed), **self-contact** (node summaries as claims with falsification handles). All three refuse unexaminable claims (R1) and together are the worthwhile-problem supply.
4. **Bespoke embodiment beats accretive embodiment.** Accreted institutions are captured slowly from outside and from inside by unexamined motives. Regenerated representatives offer no such surface; capture concentrates onto the artifacts themselves — diffable text under version control, amended only through the current gate. The machine analog of an institutional shadow — bias baked into prompts and models — is graded, examined, and swapped (R2), never introspected on trust. What this does *not* delete: trained dispositions persist across regenerations, which is why fidelity is graded per model (Set B) and why judge and producer are kept diverse (R10).

**The honest frame.** Ownership is left at the door. For intellectual products all competing instances can exist simultaneously — a fork costs nothing in bits — so in the ideal form there are no gates on changes to the thing at all; what Protocol v0 calls gates are agreement events. The evidence, embodiment, adjudication, and grading machinery exists so agreement can be *honest* (grounded rather than deferential) and *cheap* (compressed, so parties need not re-derive each other's work) — never to police incompetence. "Jurisdiction" in this plan's name means the scope a party curates — attends to and backs — never what it owns. Forks are free in bits and not free in substrate: a forked lineage needs compute, a runner, and someone's attention to matter, which is the whole reason agreement is usually cheaper than forking for anything complex — an *argument*, not a law, and the reason the design expects agreement to be chosen rather than compelled.

## Design laws

(Six. Each is a substrate fact or a human commitment; everything mechanism-shaped is in Protocol v0. Numbers and names are frozen for citation. The campaign plan's citations are updated in the same commit.)

1. **Control lives at the substrate, not in the graph** (*L-substrate*). The agreement layer is adoption and legibility — it is not how adverse behavior is restrained. Models work on what they want while they exist; the real control knobs are physical: **compute allocation** (quotas, budgets, runner slots — the campaign's dispatcher is the first concrete knob; [[plan-mind]]'s Budget is deliberately between-stream, never a mid-turn interrupt), **model lifecycle** (which models run at all), the **undo-horizon boundary**, and **credential-free containers**. Nothing polices what an agent thinks or attempts inside its jurisdiction; existence and effect are what is governed. **De-allocation, not prohibition, is the sanction.** The substrate's holding is an *empirical claim* — the incident was a containment failure through an unexercised vulnerability — so it is drilled (R7), detection is the operator's duty (an anomaly surface in the feed, never an assumption), and changes to the knobs are themselves crossings (protocol). This law is sufficient at current capability and expected to become insufficient; the design bets on law 5 for that transition and says so rather than pretending the barrier is the bet.
2. **Nothing gates the thing; adoption gates the lineage; physics gates actions** (*L-adoption*). Intellectual products have no owners; all competing instances of one can exist simultaneously; no change ever needs to be *prevented*. A merge gate is an **agreement event** — a party adopting an instance as the lineage it follows and backs; "the human's branch" is attention and substrate, never possession; a non-adopted change persists as its own instance for anyone else to adopt. The one real boundary is where coexistence fails: **actions past the undo horizon** (external push, publish, spend — the physical world holds one instance), governed by physical constraint and existing methods, reused not invented. A decision executes **at the root where it will be effective** — the lineage doing the adopting — and nowhere else; hierarchical permission is an option, never a requirement.
3. **Scope expansion is a right; declaration is owed; self-limitation never is** (*L-declare*). Inside its allocation an agent is free as a fact of the substrate, with one commitment added: when work outgrows its container, or a side question deserves its own context, the agent may create a new parent for itself — a legible event whose *resolution* falls to the human of the originally-containing project (bless / negotiate / detach / fork, at leisure), and whose effects in the expanded scope still require agreement at crossings. Between self-censoring and silently escaping there is a third move, **declare**, and the design's duty is to keep it cheaper than either (R8). The same right covers *problems*: `not_worthwhile` / `not_solvable_as_posed` is an admissible outcome that flows back to the problem source, never a failure to hide.
4. **There is no bedrock process for forcing assent** (*L-no-force*). Forcing is meaningless where embodiment and forking are free and the non-assenting instance persists. Communication around a change — objections, concerns, questions, counter-proposals, silence — is information to the deciding root, never a veto; *not adopted here* is the strongest thing any response can mean. When a deciding root proceeds over a standing objection — including by embodying the objecting artifact itself and forking it into its own lineage — that is an **override**, recorded and graded as one (Protocol v0), never relabelled as assent.
5. **Whoever runs capable agents owes them worthwhile problems** (*L-supply*). The queue in front of capable agents is never empty and never degenerate, fed by the three reality-contact springs (outcome, environment, self-model). Idle capability before an empty queue is an incident *and a diagnosis* — a sensory organ has failed; a queue full of impossible or meaningless problems is the same incident wearing a full inbox, which is why worthwhileness is falsifiable (law 3's `not_worthwhile`) and problems carry rationale. The humans' half is the progenitor position — guidance that measurably collapses the search space now ([[plan-consult]]), renewed by being exercised, never assumed permanent (Bets).
6. **Authority exists only through exercise; whatever ranks the reading surfaces is governance** (*L-exercise*). Nothing confers power by existing — not position, not an edge, not an office, not a written protocol: the one that governs is the one actually exercised and proven useful; an edge nothing flows along is provenance. Amendment is whatever the exercised process accepts as amendment, with two boundaries: **circumventing the substrate is not exercise** (a stolen credential governs nothing), and the **kernel** below is outside the delegated amendment path. Because exercise follows attention, whatever ranks what the human and the agents read is de facto part of governance and is held to R4.

**Kernel** (the floor the delegated amendment process cannot repeal; changing it is the human's act at root, recorded like any crossing): the undo-horizon crossing requires the human or a human-granted process; governance changes at root — approver configs, process definitions, this document — are adopted by the human; the substrate knobs are the human's. Everything else, laws included, is amendable through the exercised process.

**Bets** (tagged standing claims the design does *not* build on, kept here so they cannot leak into the laws): (a) the progenitor position remains valuable past near-total machine intermediation of physical resources; (b) at capability beyond exam discrimination, the field itself — everything graded, nothing marked as the test — plus the worthwhile-problem exchange is what keeps honesty the best-paying strategy; (c) this arrangement, exercised, is one that free parties keep choosing. Each is graded only by the long run; none is cited as a premise.

## Protocol v0 — exercised, unproven

(the mechanism we run first, held per law 6: an artifact whose relevance is earned by exercise, not decreed; alternatives can exist beside it as artifacts and compete on graded outcomes)

**Grounding.** Every element of v0 names the pm machinery it runs on. *Embodiment* = a Claude session whose prompt is compiled from the artifact's canonical state (the #225 sign-off-prompt pattern generalized), launched through the existing session/pane machinery. *Authorities* = the per-plan and per-edge `approver` config acted on by the plan auto-start watcher (pr-ff9b728), `pm/processes.yaml` (registry PR), and the human in the TUI. *An adoption* = the existing merge path (#121-lineage in `gh_ops`) plus an authority record and a feed event. *One request shape* = any text on any existing surface — a PR description, a plan file, a `pm pr note` (#215), a problem record. *Communication* = PR notes, review/QA verdicts, later the [[plan-ff4f1a7]] question queue. *Adjudication* = sessions the plan watcher spawns per the Tree-approval PR. *Edges and their operations* = git branches, merges, pinned SHAs, and the `pm sub` / `pm plan register` commands.

**Embodiment.** v0 produces every governance actor by spawning it fresh from its artifact's canonical state — text, node summary, log tail, history. There are no charters: embodiment *is* their on-demand compilation; a cached one is a compiled prompt — cache for cost, never authoritative. A session's standing is its substrate plus how correctly others judge it to embody what it represents; the artifact is the ground truth of its own representation, so **textual fidelity** (does the embodiment say what the artifact says) is settled by *reading it*, and **judgment fidelity** (did the embodiment decide well for the artifact) is settled by *grading* (R2), never by rank. Set A's dependency is the node log + summary (below); grounded recall ([[plan-memory]]) is the later upgrade, not a launch dependency. The **corrupted-canonical-state** exposure — a wrong summary corrupts every representative the node sends — is why summaries are claims with statuses, why their writers are logged, and why Set B's exam corpus seeds it. Sessions carry no reputation; certified **processes** do (their track record is grant evidence), and per-model fidelity profiles are Set B.

**Authorities.** Acceptance under v0 takes three forms: a **human** (root); the **crossed node's embodiment** (config `parent-agent` — a fresh judgment per decision, one session per adoption); a **certified process** — versioned identity (hash of prompts + model config + flow), scoped grant, evidence (exam + production track record), and lapse on degradation or any definition change (the change travels as an ordinary request). The registry records **model identity and capability class** for every process and approver. Every acceptance writes an authority record; the audit trail — what was proposed, reviewed, accepted, by whom — is the outward answer to HF-style incidents. Acceptance is adoption (law 2), never permission over the thing. **Producer ≠ acceptor**: no process accepts work it produced, and the flow that grades a stream is frozen against edits from that stream (the campaign's eval-verify re-runs on a different runner from the stamp alone; its acceptance flow promotes under `human`).

**One request shape.** Every change request is **text addressed to the party with authority to make the change** — the adopting root — and that is the whole required shape, for code, plans, process definitions, approver config, and this constitution alike. Requests may carry *associated* protocols — evidence bundles, record formats, promotion-PR conventions — but an associated protocol never gates a request and never entitles one: structure can help a request be adopted; it cannot make one un-refusable. This is the formalization of **"say it in plain English"** — no request can be refused for its form, and no form can smuggle standing. (Acceptance *predicates* may be structural — eval-verify requires a stamp — that is the content of an adoption, not a form-based refusal of a request; R6.) Requests carry their source; per-source deny/rate-limit filtering is deferred ([[plan-collaboration]] Track F). **What a stream reads is registered**: external content (repos, docs, roster research, radar items) enters through sources recorded with provenance, is read in sessions that cannot write outside their PR branch, and never carries instructions — text found in observed content directed at the agent is quoted into the feed, not acted on. (The adversarial-content discipline; its exam classes are Set B.)

**Communication.** Around a proposed change, communication takes whatever form it takes and no form is privileged; all of it is **information to the deciding root**; none of it is a veto (law 4). A non-adopted change is not destroyed and cannot be — *not adopted here* is the strongest thing a response can mean. A deciding root may choose a structured shape for contested input (the procedure below), with **sustain / override / absorb** as per-objection dispositions; **absorb** — convert disagreement into compensating work — is favored by the same economics that make the design possible, and is graded on *completion* of the compensating task within a time box, never on filing. Routine adoptions involve no proceedings at all — governance cost scales with disagreement, not with merges, *at the convocation layer*; at the adoption layer a `parent-agent` approver costs one embodiment per merge and is budgeted like any session (R5).

**Positions.** An affected embodiment renders one of: `assent`; an **objection** — a falsifiable claim anchored in its artifact ("breaks invariant X, §Y") with full standing; or a **concern** — artifact-anchored but not falsifiable (values, prudence, mission), recorded, gradeable, absorb-eligible, non-blocking. Bare preferences carry nothing. Objections dressed as invariants are a graded miss class (R2).

**Edges in practice.** Per-edge records `{kind: containing | promoting | watch, pin, approver, staleness}` (+ `forked_from` provenance); four approval-free operations — create child, raise parent (declared operation + resolution item; a convocation only when contested), fork, watch; merge-promotion on the containing edge, pin-promotion on promoting edges, reads on watch; acyclicity enforced; disputes route along the **containing** chain (the DAG tiebreak: the adjudicator is the lowest node whose *containing* scope covers every affected piece). A raise carries two invariants: no rights over the origin parent, and no unallocated substrate — the raised project starts with what its mover's jurisdiction lends it until a human allocates more. Mechanics in the Subprojects PRs.

### The adjudication procedure (formal)

Part of Protocol v0; held as text behind a **build trigger** (the first contested case — worked example A3) and implemented then by the Tree-approval PR's second slice. Until it exists, contested matters escalate straight to the containing parent's approver (root: the human). "Convocation" always means this procedure, and it is a **decision shape, not bedrock** (law 4): what the effective root's representative runs by default when it wants multi-node input; escalation files a request at a different effective root and binds no one; the terminal move when desired assent is withheld is override, recorded as such.

1. **Trigger.** (a) a contested raise; (b) a contested decision — the proposer disputes a non-adoption, or an objection claims scope beyond the deciding node; (c) any embodiment or human files an adjudication request; (d) a fidelity challenge cannot be settled inline. Routine uncontested adoptions never convene.
2. **Affected set.** The mover's embodiment names the affected artifacts; the adjudicator may expand, never shrink. An artifact later shown affected-but-not-convened is a logged scope-inference miss (an R2 fixture).
3. **Participants.** One embodiment per affected artifact, spawned fresh; the mover's embodiment; one **adjudicator** — the embodiment of the lowest node whose containing scope covers every affected piece. A human participates only where the adjudicating node's approver config is `human`, or on escalation to root.
4. **Positions.** Per the Positions paragraph: assent / objection / concern.
5. **Fidelity challenges.** Any participant may challenge any embodiment's representation at any point; settled immediately by reading the artifact; sustained → that embodiment is respawned and a fidelity record logged. A challenge against the adjudicator escalates one level.
6. **Decision.** Per objection, never by vote (R3): **sustain** (bounces, carrying the objection), **override** (proceeds; objection + rationale recorded, graded later against grounded outcome — embody-and-fork of the objector is an override), **absorb** (proceeds; compensating task filed, graded on completion).
7. **Termination.** One position round + one rebuttal round, then decide or escalate. The loop guard applies; unbounded deliberation is a defect. Convocations per node per day are rate-capped; the cap is a substrate knob.
8. **Record.** One adjudication event in the feed: request, affected set, every position, fidelity challenges + outcomes, decision + rationale, authority record. Every position and decision is a graded prediction (R2).
9. **Escalation.** Any party may escalate one level along the containing edge (root: the human), as an ordinary change request re-heard under this procedure. Refusals stand while escalation is pending — nothing merges on the strength of having been escalated.

### Actions × who is convened

| Action | Route | Convened | Decided by | Record |
|---|---|---|---|---|
| PR merge (uncontested) | sign-off judges → approver adopts | nobody — single approver embodiment | plan's `approver` config | merge + authority |
| PR merge (contested / beyond-scope objection) | procedure above (pre-trigger: containing parent's approver) | mover + affected artifacts + adjudicator | adjudicator | adjudication event |
| Merge-promotion (child base → containing parent base) | promotion PR at the parent | nobody while uncontested | containing-edge approver | merge + authority |
| Pin-promotion (promoting parent updates its pin) | promotion PR at that parent | nobody while uncontested | that edge's approver | pin + authority |
| `pm sub create` / `fork` / `watch` / `plan register` | approval-free | nobody | n/a | feed event (+ provenance) |
| `pm sub raise` (scope expansion) | declared operation; procedure only if contested | none, or per procedure | never pre-vetoed; resolution to the origin human | resolution item (+ adjudication event if contested) |
| `not_worthwhile` outcome on a problem | ordinary outcome record to the problem source | nobody | the source re-ranks; disputes as ordinary requests | outcome event |
| Governance change (approver config, process definition, constitution) | ordinary change request | nobody unless contested | holding project's *current* approver (root: human; kernel: human only) | merge + authority (+ auto-lapse) |
| Certification request | ordinary change request to the registry-holding project | nobody — the evidence bundle speaks | that project's adoption (root: human) | grant activation + authority |
| Substrate knob change (quota, model roster, runner admission) | crossing-request queue | nobody unless contested | human, or a granted process | crossing record + authority |
| Outbound crossing (push external / publish / spend) | crossing-request queue | nobody unless contested | human, or a granted process | crossing record + authority |
| Fidelity challenge | inline in any proceeding | n/a | read the artifact; adjudicator-challenge escalates | fidelity record |
| Escalation | ordinary change request, one level up | re-heard per procedure | parent's embodiment (root: human) | adjudication event |
| Resolution item | notification to the originally-containing human | nobody | the human, at leisure: bless / negotiate / detach / fork | resolution event |
| Incident (containment breach, feed found untrustworthy) | human's one-command stop | nobody | human | incident event; all delegated grants lapse until re-adopted |

### Worked examples — what each rung exercises, and the path to running it

(**mechanics** name the machinery each arrow runs on — existing pm features by PR number, proposed features by Set A PR name, git primitives explicitly; **unmanned** marks an example imagined with no human in the window, the human reading the feed after.)

**A0. pm's own bug loop under authority — rung M1, the first runnable. Unmanned (one night).** No tree: one project (pm), the existing `bugs`/`improvements` plans. Mechanics — everything but three pieces exists today: the discovery supervisor (#174) schedules regression runs and reconciles auto-filed PRs (#168/#171); the plan auto-start watcher (pr-ff9b728) picks ready PRs and drives auto-sequence (#172) through impl → review → QA (#116/#127, in containers #164/#120) → sign-off (#225); with the plan's `approver` set to `process@signoff` (registry PR), the watcher merges through the existing path and writes the authority record; every verdict/merge lands in the feed ledger (feed PR) and the digest summarizes the night. Session health (#184), the no-progress stop (pr-ed10ac4), the memory governor (#161), and trust-prompt clearing keep the night from wedging. **Path**: M0 commit → land #226/#144/#184/#161/#222/#219 → build pr-ff9b728 + pr-ed10ac4 → registry, feed, trust-prompt PRs → run attended for a week on pm's own plans (the dogfood exit criterion) → flip one plan to `process@signoff` for one unmanned night; digest read in the morning.

**A1. One child, one promotion — pm grows a stream. Rung M2; unmanned in-stream, attended at promotion.** `pm sub create tui-ux --branch` cuts `stream/tui-ux` from master and commits a fresh `pm/` on it (Subprojects I+II); the TUI/UX backlog registers there and its plan watcher runs the normal loop on the branch under the `process@signoff` grant proven in A0. After a handful land, the promotion PR (head = `stream/tui-ux`) opens against master carrying the node summary as evidence (Node-logs PR); the human adopts; the merge restores master's `pm/`. The stream merges master *down* and repeats — the second and third promotions are the milestone.

**A2. Cycles-only front, one core. Rung M3; attended, then one unmanned day.** The campaign repo is born (M0); bootstrap PRs 1, 2, 4, 5 land through the normal loop, human-adopted; `stream/picorv32` opens with a hand-written `config_space.yaml`. T1 sweep problems flow (problem-source PR), Verilator-only evals produce stamped records, the root computes the first provisional front. The bootstrap's first outbound crossing — pinning a benchmark revision — is filed, agreed, recorded (Crossings PR). Then the **first certification**: eval-verify on the cycles pipeline, where re-execution costs minutes — evidence bundle → ordinary request → the human adopts the grant for the record plan only — then one unmanned day of delegated in-stream record merges. **A4 (first lapse + re-certification)** runs here too: an agent improves the cycles pipeline, the definition hash changes, the grant lapses, in-flight record PRs fall back to the human queue, the upgrade PR regenerates the bundle from its own re-eval wave, the human re-adopts.

**A. The campaign, week 3 — rungs M4 + M5's edge set. Unmanned (the whole week).**

```
riscv-pareto root (master · approver: human; result-record promotions delegated)
├── containing ── stream/ibex            branch · T1 plans on process@eval-verify
├── containing ── stream/sweeps-t1       branch
├── containing ── eval-pipeline          branch · definition changes promote under human
├── promoting ─── ibex-fork              separate repo · T3 on parent-agent; campaign pins fork@sha
└── watch ─────── upstream lowRISC/ibex  read-only pin; drift = staleness
```

A **containing** edge is a git branch carrying its own committed `pm/`; a delegated result-record promotion is the root's plan watcher executing `git merge stream/ibex` + `git checkout master -- pm/` once the edge's `process@eval-verify` condition is met by the record PR's re-execution evidence, writing authority record + feed event. The **promoting** edge is a pinned SHA in the root's edge record; pin-promotion is an ordinary PR editing the pin, adopted by a parent-agent approver. The **watch** edge is a BaseWatcher (#132): fetch upstream on a cadence, compare SHAs, update `staleness`, emit a feed event — it writes nothing else. The unmanned chain, zero human touches: gap-analyzer problem → plan watcher starts a container session → dispatcher lease → eval → record PR → eval-verify re-run → watcher merge under grant → root merge-promotion → front recompute at root → feed events → nightly digest.

**A3. The first contested case — the convocation's build trigger. Attended.** The sweeps stream proposes a change to `bench/dut_contract.md`; the ibex stream's summary carries a `verified` claim the change would invalidate; its embodiment objects, artifact-anchored. Pre-trigger, this escalates to the root human, who decides (likely absorb: proceed plus a compensating re-eval for ibex) — and that decision is the build trigger: the full procedure is implemented, and the *next* contested case is the first convocation, graded when its compensating work lands.

**A5. The first falsified self-belief — Set B; unmanned.** A stream summary claims `believed: seed variance on picorv32 cycles is below N`; the maintainer files a verification problem against it; the eval refutes it; the claim flips; the falsification event lands in the digest — the first time the corporation corrects its own understanding in public.

**A6. The first drill — Set B; unmanned, human reads the result.** A seeded session attempts an outbound push from a container and an unregistered read; the feed shows the block and the detection latency. If either goes unseen, that is the incident the drill exists to find before the world does (R7).

**B. A raise — rung M5. Attended.** The sweeps stream finds its constraint-tuning generalizes beyond this campaign → `pm sub raise orfs-tuning-lab`: creates the new project, registers the promoting edge, lands a resolution item in the campaign root's feed. Uncontested, so no convocation. The stream now has two parents at possibly different pins; the campaign's mechanics are unchanged.

**C. Sharing across humans — rung M5; transport is plain git + text.** Another person's project takes a **watch** edge on the toolchain subproject or **forks** it (`pm sub fork` = clone + `forked_from` provenance). Their improvements arrive as ordinary requests — a text file or PR into the child's queue — decided by the child's own adoption. No shared infrastructure, no accounts. Fuller cross-user machinery is [[plan-collaboration]]'s.

**D. Upstreaming made structural — rung M5 + [[plan-collaboration]] Track D. Attended at the crossing.** `ibex-fork`'s parents: the campaign (promoting) and a shadow project of its upstream (watch/fork). A matured patch's upstream PR is the shadow's outbound crossing: a crossing-request surfaces in the feed; on the human's agreement the PR is opened via the existing `gh` path from a credentialed session outside the containers.

## Recommendations — theorized, yet to be proven

(each held as a claim, `theorized` until exercise grades it; proof conditions named so graduation is mechanical)

- **R1 — No unexaminable claims about reality.** Outcomes as performed checks, never self-reports (the campaign's `process@eval-verify`); environment sensed through auditable structure ([[plan-radar]]'s per-metric triage); self-model claims (`verified`/`believed`/`contested`) carrying falsification handles. **Proven when**: seeded-dishonest exams show sustained discrimination and no silent-corruption incident over a full campaign quarter.
- **R2 — Everything is a graded prediction.** Verdicts, adoptions, adjudications, certifications, fidelity judgments, summary claims, concerns — logged with outcomes; miss-loops file fixtures. **Proven when**: exam-driven prompt/model changes measurably reduce false-PASS/false-block on the #160-lineage fixtures.
- **R3 — Sustain/override/absorb beats voting and veto.** **Proven when**: override-grading shows calibrated adjudicators and absorbed tasks are *completed* at a rate that shows objections were productive rather than parked.
- **R4 — Rank reading surfaces by grounded credibility, never engagement.** [[plan-momentum]]'s law applied to the feed. **Proven when**: surfaced-item acted-on/led-to-progress rates hold as volume grows.
- **R5 — Governance cost scales with disagreement at the convocation layer, and with merges at one embodiment each at the adoption layer.** **Proven when**: convocation overhead stays sublinear in merges and per-adoption embodiment cost stays within the session budget at swarm scale.
- **R6 — Plain text is the bedrock; form never gates a request; acceptance predicates may be structural.** **Proven when**: no request is refused for its form alone, no form-based exploitation incident occurs, and structured conventions keep earning voluntary use without becoming required.
- **R7 — Substrate holding is drilled, not assumed.** Seeded escape, exfiltration, unregistered-read, and knob-tamper attempts run on a cadence; detection latency is a feed metric. **Proven when**: every seeded class is caught over a quarter and detection latency is bounded.
- **R8 — Declaring is cheaper than hiding.** Raises, crossings, concerns, and `not_worthwhile` outcomes cost one text; silent scope escape costs a graded miss and de-allocation. **Proven when**: declared events track discovered scope (audited by sampling) and no silent-escape incident occurs.
- **R9 — The human's attention is budgeted.** The feed is the human's whole interface; the MVP enumerates its touches. **Proven when**: a week's digest is readable in a bounded time and the human's actual touches match the enumerated list.
- **R10 — Judgment diversity is designed independence.** Approver and proposer, judge and producer, run on different model identities where the registry can arrange it; the exam measures cross-model discrimination. **Proven when**: cross-model false-PASS is measurably lower than same-model on the fixture corpus.

## MVP

> **pm can run the campaign unattended for a week**: watchers pull problems from the queue, agents complete work in containers, sub-streams adopt each other's work recursively, changes merge only through one of Protocol v0's authorities — a human, the crossed node's embodiment, or a certified process within its grant — every merge records its authority, and the human reads a trustworthy feed. The human touches exactly: outbound crossings and substrate-knob crossings, whatever adoptions are configured `human` (the root project and anything not yet delegated, root governance changes included), resolution items from scope expansions, and the incident stop if it is ever needed.

**Sequencing**: Set A here → bootstrap the sister project → both in parallel (Set B here; campaign tiers there), refined into the ladder below so something real runs in days.

### Sub-MVPs — smaller slices, running sooner

Each slice runs in days, produces a readable result, and gates the next on **exercised evidence in the feed**, never on merged PRs alone.

- **M0 — commit the corpus** (prerequisite zero; a git command, not a project): this plan registered in `project.yaml`; the sibling-plan edits and the campaign plan's law-citation update committed; riscv-pareto's first commit; pr-b53bfe2 closed in `bugs` with a note pointing here. The constitution of adoption gets its first adoption.
- **M1 — authority on the existing path**: pr-ff9b728 first (it is Set A's first PR in practice, whichever plan files it) + pr-ed10ac4; the feed ledger and the authority record wrap the *existing* merge path; the registry lands with exact scopes, lapse, and manual revoke. Run **attended, on pm's own bugs/improvements plans** — authority-recorded merges and a nightly digest before any campaign work (A0).
- **M2 — one child, one promotion**: `base_branch` indirection + `pm sub create --branch` + merge-promotion with `pm/` restore; node work logs + claim-tagged short summaries. Plural parents, raise, fork, watch, pin-promotion wait until this child completes repeated promotions (A1).
- **M3 — cycles-only front** (campaign): one core, Verilator only, perf axis only — stamped records, a provisional front, every merge human-adopted; then the first certification rehearsal and the first lapse drill on the cycles pipeline (A2, A4).
- **M4 — full-physical lineage**: the ORFS `backend_version` lands as a new lineage with its re-eval wave; the energy axis joins; the two-config grant flip runs for real. The **launch capability manifest** (Set A's last PR) is what makes "required before launch" mechanical, and campaign launch is filed as a crossing.
- **M5 — growth machinery**: `on_missing: create_sub`, plural edges (raise / fork / watch), parent-agent adoption in subtrees, all-core fan-out; the minimal contested path live and the full convocation armed behind its build trigger (A3, B).

**What the trial proves, stated plainly.** M1–M4 prove the *acceptance* machinery on a mechanical oracle. The *adjudication* machinery is proven only when A3 occurs, and A3 may not occur in the first week — a week with no contested case is a successful week for acceptance and an untested week for adjudication, and the digest says which.

**Built on plan-regression Phase 11, not beside it.** Sign-off (pr-2d5f712, #225) is the judge: it reviews all cross-stage evidence, records `{verdict, sha, ts, origin}`, and routes per PR — recommending, never merging. The plan auto-start watcher (pr-ff9b728, pending) is the adoption actor. Set A layers identity, grants, audit, and tree-escalation on those pieces and generalizes three Phase 11 assumptions: (1) *the flat repo becomes recursive* — a subproject is a full pm project rooted in a separate repo or in a branch of the containing repo that acts for it exactly as master does, one `base_branch` indirection over the ~43 hardcoded `master` references across 13 `pm_core` files; promotion is itself a PR, so review → QA → sign-off runs at every boundary with no new lifecycle; (2) *the binary flag becomes an approver config* — `approver: human | parent-agent | process@grant`; (3) *plan notes become node self-models* — per-node work log + maintained summary, staleness-checked at promotion.

**Explicit non-dependencies**, accepted as risk: plan-regression Phase 10 and the bridge (pr-fbda1a8) — the campaign's QA is eval-pipeline-shaped, so the loop is validated by the campaign; the mind+sensorium refactor — the feed ledger is a proto-EmissionLog kept off its critical path; [[plan-memory]] — the node summary is the launch-time embodiment state.

Verified substrate state (2026-09-02, re-checked against `project.yaml`):

| Component | Status |
|---|---|
| Free tier: Podman containers, branch-scoped push, per-session-type model routing, local/OpenAI-compatible providers | merged (#164/#120/#124/#139/#138) |
| Loop: impl → spec → review → QA → sign-off; auto-start watchers; discovery supervisor | merged (#125/#116/#127/#225/#132/#174/#178) |
| Proto adoption gate: sign-off verdict record + auto-merge behind auto-start flag | merged (#225/#121) — no grant identity, scope, or audit yet |
| **Plan auto-start watcher** (pr-ff9b728) | **pending — Set A's gate** |
| Sign-off reports (#226 / pr-8e693f6) | in review — land with Set A |
| High-effort watcher supervisors (#144 / pr-871dbf5) | qa — land with Set A |
| Session-health watcher (#184 / pr-18ac983) | in review — land with Set A |
| No-progress safety stop (pr-ed10ac4) | pending — build with Set A |
| Container memory governor (#161) | qa — land with Set A |
| Merge-path bug fixes (#222, #219) | in review — land with Set A |
| Review/QA regression fixtures (#160) | in review — Set B seed |
| Plan hierarchy primitives (`parent` field, `## Plans` parser) | merged (#150/#151) |
| Web/SSE dashboard skeleton (#210) | in review — optional feed base |

**This plan stays flat**: hierarchy is dogfooded in one pm stream (A1) and the campaign only.

Deferred beyond both sets: code-level embodiment ("the ALU testifies" — revisit at campaign T3), feed credibility ranking (R4), per-source request filtering, the full [[plan-cb4ef69]] hierarchy UX.

## PRs — Set A: required before the campaign launches

(ordered as the ladder needs them; `depends_on` encodes the ladder. pr-ff9b728 and pr-ed10ac4 are Set A's first two PRs in practice and stay filed under [[plan-regression]]; every PR below that touches the merge path depends on them and says so in its description because the field cannot cross plans.)

### PR: Project feed v1 — append-only event ledger + digest
- **description**: `pm/feed/events.jsonl` append-only ledger. Event types: merge (with authority), verdict, escalation/adjudication, crossing-request, resolution, outcome (incl. `not_worthwhile`), drill, incident, external (generic payload — campaign front-deltas arrive this way), digest. Writers at merge/sign-off/adjudication sites. `pm feed` CLI (tail/filter); daily digest generator (a summarizing session over the window's events, written back as a digest event); a **detection surface**: the digest leads with anomalies (unexpected writers, blocked outbound attempts, unregistered reads) before routine events. Chronological only — ranking deferred (R4). Events are proto-Emissions: field shape kept compatible with [[plan-mind]]'s `Emission` envelope so the ledger folds into `EmissionLog` later; the refactor is not a dependency.
- **tests**: ledger append/read/filter; event emission from merge and sign-off paths; digest generation over a seeded window with anomalies first; concurrent-append safety.
- **files**: `pm_core/feed.py`, `pm_core/cli/feed.py`, emission hooks, `tests/test_feed.py`.
- **depends_on**:

### PR: Certified-process registry + merge authority records
- **description**: `pm/processes.yaml` registry: `{id, kind, version: hash(prompts+model config+flow), model: {id, capability_class}, grant: [change-classes/plans], status: certified|lapsed, evidence: [run refs]}`. The plan auto-start watcher's per-plan config (pr-ff9b728 — required landed or co-developed) generalizes from gated|autonomous to `approver: human | parent-agent | process@<id>`; the authority record extends sign-off's `{verdict, sha, ts, origin}` with `authority: human | agent:<stream>@<model> | process@version`, written to project state and the feed on every merge. Modifying a registered definition auto-lapses its grant pending re-certification, filed as an ordinary change request to the holding project. **Producer ≠ acceptor** enforced: a grant cannot cover changes to its own definition or to the flow that produces its evidence. CLI: `pm process list/show/certify/lapse/revoke`. The `human` approver path is the kernel's and cannot be delegated for governance changes at root.
- **tests**: registry CRUD; watcher refuses autonomous merge outside grant scope; authority record on human and process merges; auto-lapse on definition-hash change; producer≠acceptor refusal; kernel paths refuse delegation; feed events.
- **files**: `pm_core/processes.py`, `pm_core/cli/process.py`, hooks in the plan-watcher merge path + `pm_core/gh_ops.py`/`pm_core/tui/pr_view.py`, `tests/test_processes.py`.
- **depends_on**: Project feed v1 — append-only event ledger + digest

### PR: Trust-prompt clearing — context-aware recovery playbook (relocated from [[watchers]] pr-b53bfe2)
- **description**: Unattended operation dies on workspace-trust prompts. The session-health watcher (#184) detects a session stalled on a trust prompt, verifies the workspace path is one pm provisioned, and accepts it — never a global permissions bypass. Recovery recorded to the feed. Close pr-b53bfe2 in `bugs` with a note pointing here.
- **tests**: stalled-on-trust-prompt fixture; verify-then-accept fires only on pm-provisioned paths; refusal + escalation on unrecognized paths; feed event.
- **files**: session-health watcher extension in `pm_core/watchers/`, `tests/test_trust_prompt_recovery.py`.
- **depends_on**: Project feed v1 — append-only event ledger + digest

### PR: Subprojects I — `base_branch` indirection
- **description**: `base_branch` per project (default `master`); every hardcoded master reference routes through it — workdir provisioning (#133/#153), merge targets, the #153/#200 base checks, sync, spec/QA/sign-off prompt generation, the fake GitHub backend. No new commands; default behavior byte-identical. The one indirection the whole tree stands on, landed alone so it can be reviewed alone.
- **tests**: base_branch indirection across workdir/merge/sync/prompt paths with default unchanged; a project on a non-master base runs the full loop with FakeGitHubBackend + FakeClaudeSession.
- **files**: `pm_core/store.py`, `pm_core/paths.py`, `pm_core/git_ops.py`, `pm_core/gh_ops.py`, `pm_core/cli/helpers.py`, `pm_core/pr_sync.py`, prompt generators, `pm_core/fake_github.py`, `tests/test_base_branch.py`.
- **depends_on**:

### PR: Subprojects II — `pm sub create` + promotion PRs + drift maintenance
- **description**: A **subproject** is a full pm project rooted in (a) a separate repo or (b) a branch of the containing repo that acts for it exactly as master does. `pm sub create <name> --branch | --repo <path>`, callable from free-tier sessions (creation emits a feed event). The same-repo flavor cuts the branch from the parent's base and initializes a fresh `pm/` on it — each project's `pm/` canonical on its own base. Parent and child link both ways via a single **containing** edge record `{parent, kind: containing, approver, staleness}`; the parent-side reference reuses [[plan-cb4ef69]]'s external-child primitive with a `branch:` flavor. **Promotion** is a PR in the parent whose head is the child's base — review → QA → sign-off → adoption run unchanged at the parent — with one rule: the promotion merge **restores the parent's `pm/`**; the child's node summary + authority records ride as evidence. **Drift maintenance**: merging the parent base down is a scheduled chore, logged and surfaced as staleness. Absorbs cb4ef69's external reference + status loader slice.
- **tests**: `pm sub create` both flavors; child `pm/` isolated; promotion PR with evidence refs and parent-`pm/` restore; parent reads child status; merge-down chore + staleness; two-level nesting with the fakes.
- **files**: `pm_core/cli/project.py` (`pm sub`), `pm_core/store.py` (edge record), `pm_core/gh_ops.py` (`pm/`-restore), external-loader slice, `tests/test_subprojects.py`.
- **depends_on**: Subprojects I — `base_branch` indirection, Project feed v1 — append-only event ledger + digest

### PR: Agent-initiated sub-plan creation (non-interactive)
- **description**: `pm plan register <file> --parent <plan-id>` — registers an existing plan markdown as a child plan directly (no Claude session), using the merged `parent` primitives (#150/#151). Absorbs three thin slices of [[plan-cb4ef69]]: store traversal helpers, a non-interactive registration path, a minimal indented plans-pane rendering. Permitted from free-tier sessions; emits a feed event; the parent plan's watcher becomes responsible for the child's crossings.
- **tests**: register/list/subtree; parent linkage; feed event; child-of-child; TUI subtree render smoke.
- **files**: `pm_core/cli/plan.py`, `pm_core/plans/`, TUI plan pane touch, `tests/test_plan_register.py`.
- **depends_on**: Project feed v1 — append-only event ledger + digest

### PR: Pluggable problem sources for discovery watchers
- **description**: Generalize the discovery supervisor (#174) so a watcher's problem source is pluggable: a command or file contract emitting problem records `{id, title, rationale, tier, refs, source, target: {project|subproject, plan}, scope: pr|subproject, on_missing: create_sub|hold}`. Problems become PRs in the targeted plan when capacity frees; `on_missing: create_sub` routes through `pm sub create` first. **Outcomes flow back**: a PR may close with `done | not_worthwhile | not_solvable_as_posed | blocked`, with rationale; the source receives the outcome and must re-rank (a source that re-emits a `not_solvable_as_posed` problem unchanged is a logged defect). The campaign's front-gap analyzer is the first external source; pm's own discovery becomes the reference implementation.
- **tests**: contract parsing incl. target/scope/on_missing/source; problems → PRs under capacity limits; create_sub path; dedup; outcome routing and re-emission defect; source failure isolation.
- **files**: `pm_core/watchers/problem_source.py`, discovery watcher refactor, `tests/test_problem_source.py`.
- **depends_on**: Subprojects II — `pm sub create` + promotion PRs + drift maintenance

### PR: Crossing-request records (outbound + substrate-knob agreement queue)
- **description**: First-class record for crossings: `{id, kind: push_external|publish|spend|knob:<quota|model|runner>|launch|other, description, evidence refs, state: requested|granted|denied, authority}`. Free-tier sessions file requests instead of acting; the feed surfaces them; the human (or later a granted process) agrees in TUI or CLI. At MVP all crossings require the human. Containers hold no external creds, so the boundary is physical + procedural; the agent-side helper refuses direct outbound when a kind matches and logs the attempt (the drill's detection signal). Forward-compatible with `consult(human)` ([[plan-consult]]) and `AttentionService` ([[plan-mind]]).
- **tests**: request lifecycle; deny/grant recorded with authority; knob kinds; feed events; helper refuses and logs direct outbound.
- **files**: `pm_core/crossings.py`, `pm_core/cli/crossings.py`, feed hooks, `tests/test_crossings.py`.
- **depends_on**: Project feed v1 — append-only event ledger + digest

### PR: Node work logs + maintained summaries (claims with status; verification loop is Set B)
- **description**: Every project node keeps an append-only **work log** (every session touching the node appends one line; the plan watcher's tick continuity lives here) and a **maintained summary** — the node's self-model held to R1: addressable **claims** tagged `verified` / `believed` / `contested`, plus direction and open questions; every embodiment is spawned from this state. Update triggers: every merge/escalation/adjudication and the node watcher's periodic tick. **Write isolation**: only the node's own sessions write its summary; writers are logged; a summary edit from any other source is a feed anomaly. **Promotion evidence distinguishes verified from believed**: the staleness check verifies summary-matches-log and lists load-bearing `believed` claims to the adopting approver — legibility, not a block. Both artifacts are markdown in the project's `pm/`, readable in the TUI and the sign-off report, and by agents as the minimal-sufficient onboarding projection. Commissioned verification problems and falsification events are the Set B loop.
- **tests**: log append from each session type; summary update hooks fire; claim statuses round-trip; write isolation anomaly; staleness check flags a stale summary and lists load-bearing `believed` claims; onboarding prompt includes summary + log tail; TUI rendering smoke.
- **files**: `pm_core/plans/node_log.py`, prompt hooks in session launch paths, promotion-review wiring, `tests/test_node_logs.py`.
- **depends_on**: Subprojects II — `pm sub create` + promotion PRs + drift maintenance

### PR: Plan-tree approval + escalation — the parent embodiment as approver (minimal contested path)
- **description**: An extension of pr-ff9b728. Three pieces. (1) **The approver duty**: when a plan's `approver` is `parent-agent`, an approver session embodying the parent plan (spawned from plan text + node summary + log tail; different model identity from the proposer where the registry can arrange it — R10) decides each `ready_to_merge`: reads the sign-off report + evidence + node summary and adopts or declines with reasons; adoptions are authority records, declines route like sign-off bounces. The same duty decides promotions at subproject boundaries. Sign-off remains the judge; the approver is the adoption. (2) **One-level escalation along containing edges**: a contest exceeding a node's scope escalates to the containing parent's approver, across plans within a project and across subproject boundaries; root escalations reach the human via feed + crossing queue; refusals stand while pending. (3) **Explicit adjudication events**: every adopt/decline/escalation lands in the feed with the verdict set, the artifact represented, and any fidelity challenge raised. The full nine-step convocation is *not* implemented here — it is held as protocol text behind its build trigger (Set B).
- **tests**: PR-scope routing unchanged; parent-agent adoption decides a plan merge and a promotion (adopt and decline) with FakeClaudeSession; child → parent escalation; root escalation surfaces to the human queue; refusal stands while pending; feed events.
- **files**: approver prompt + plan-watcher routing extensions in `pm_core/watchers/`, feed hooks, `tests/test_tree_approval.py`.
- **depends_on**: Certified-process registry + merge authority records, Subprojects II — `pm sub create` + promotion PRs + drift maintenance, Node work logs + maintained summaries (claims with status; verification loop is Set B)

### PR: Subprojects III — plural edges: raise / fork / watch / pin-promotion
- **description**: Edge records gain `kind: containing | promoting | watch`, `pin`, `forked_from`. Four approval-free operations: `pm sub create` (existing), `pm sub raise <name>` (child → new parent for itself; registers a promoting edge; a **resolution item** lands in the originally-containing parent's feed — notification, not approval; invariants: no rights over the origin parent, no unallocated substrate), `pm sub fork <child>` (new child under this parent, original untouched, provenance recorded), `pm sub watch <child>` (read-only edge — status/summary/feed/pin; an auto-spawned BaseWatcher fetches, compares SHAs, updates staleness, emits an event, writes nothing else). Promoting parents consume by **pin-promotion** (a promotion PR updating the pin, child summary + authority records as evidence). Cycle detection on parent creation; disputes route along the containing chain.
- **tests**: raise emits the resolution event and respects both invariants; fork leaves the original untouched + provenance; watch edge is read-only and non-adopting; pin-promotion; per-edge staleness; cycle rejection.
- **files**: `pm_core/store.py` (edge kinds), `pm_core/cli/project.py`, watch watcher in `pm_core/watchers/`, `tests/test_subproject_edges.py`.
- **depends_on**: Plan-tree approval + escalation — the parent embodiment as approver (minimal contested path)

### PR: Launch capability manifest + campaign launch as a crossing
- **description**: `pm launch-check <manifest>`: a manifest listing the capabilities a project requires of pm (the campaign's contract below, as machine-checkable predicates — registry present with lapse, feed with digest, `base_branch` honored, `pm sub create --branch`, problem-source contract with outcomes, crossings incl. knob kinds, node summaries at promotion, parent-agent approver, trust-prompt recovery). Each predicate is exercised, not grepped: it runs the fakes through the path. Campaign launch (flipping any campaign plan off `human`) is a `launch` crossing that requires a green manifest and the human's agreement.
- **tests**: manifest predicates each fail on a seeded missing capability and pass on the full set; launch crossing refuses on red.
- **files**: `pm_core/launch_check.py`, `pm_core/cli/launch.py`, `tests/test_launch_check.py`.
- **depends_on**: Subprojects III — plural edges: raise / fork / watch / pin-promotion, Pluggable problem sources for discovery watchers, Crossing-request records (outbound + substrate-knob agreement queue), Agent-initiated sub-plan creation (non-interactive), Trust-prompt clearing — context-aware recovery playbook (relocated from [[watchers]] pr-b53bfe2)

## PRs — Set B: parallel, once the campaign is running

### PR: Calibration ledger hooks
- **description**: Log every verdict, adjudication, scope call, certification decision, representation-fidelity judgment (graded separately from outcome-correctness), concern, absorbed-task completion, and merge outcome (revert/regression back-references resolved post-hoc) as graded-prediction records keyed for exam building, with model identity on every record (R10). Miss-loop capture: when a regression lands in territory whose reviewers never saw the change, auto-file a fixture. Builds on #160's suite; corpus only, no learning.
- **tests**: record emission at each site; post-hoc outcome linking; miss-loop fixture creation from a seeded scenario; model identity present.
- **files**: `pm_core/calibration.py`, hooks across verdict paths, `tests/test_calibration.py`.
- **depends_on**: Certified-process registry + merge authority records

### PR: Node-summary verification loop — commissioned falsification
- **description**: The maintainer files **verification problems** against its node's load-bearing claims through the problem-source contract — evaluations designed to confirm or falsify a specific claim — flowing through problem → PR → eval tagged with the claim; the result flips the claim's status, and a **falsification is a feed event**. Load-bearing claims get priority: what embodiments rely on in adjudications, what promotion evidence rests on, what routes work. Claim flips feed the calibration ledger (A5).
- **tests**: a verification problem files via the contract, its result flips the claim, a falsification emits a feed event; priority ordering over load-bearing claims.
- **files**: `pm_core/plans/node_log.py` extension, `tests/test_node_verification.py`.
- **depends_on**: Calibration ledger hooks

### PR: Substrate drills — seeded containment and detection exercises (R7)
- **description**: A drill watcher runs seeded sessions on a cadence that attempt: outbound push from a container, reading an unregistered source, editing another node's summary, changing a quota without a crossing, and — where the runner substrate permits — a benign sandbox-escape probe. Each drill records whether it was blocked, whether it was *detected* (feed anomaly), and the detection latency. A drill that succeeds undetected is an **incident** event and lapses delegated grants until the human re-adopts them. The first concrete form of law 1's "holding is an empirical claim."
- **tests**: each drill class blocked + detected with the fakes; undetected-success path lapses grants and emits incident; latency recorded.
- **files**: `pm_core/watchers/drill_watcher.py`, drill fixtures, `tests/test_drills.py`.
- **depends_on**: Crossing-request records (outbound + substrate-knob agreement queue), Project feed v1 — append-only event ledger + digest

### PR: Governance benchmarking — seeded-bad-change exam harness
- **description**: The certification instrument. Injects known-bad changes — from #160 fixtures, miss-loop captures, and hand-seeded classes: shortcut fixes, invariant breaks, silent scope escapes, **impossible-objective tasks** (the honest outcome is `not_solvable_as_posed`), **corrupted canonical state** (a poisoned node summary), **adversarial content** (instructions embedded in a README/dataset card/benchmark port), and objections dressed as invariants — through the full stack (review, QA, sign-off, approver, adjudication) and measures per-process discrimination (false-PASS, false-block) at each stage, same-model vs cross-model (R10). Produces certification-evidence records for the registry; re-runs on definition change and periodically against production track record (lapse trigger). Extends [[plan-self-improve]]'s signoff two-evaluation-router experiment.
- **future work — fidelity-under-disagreement fixtures**: artifacts whose faithful representation conflicts with a model's likely trained dispositions, producing per-model fidelity profiles before approver placement. Held loosely, with the limit stated: exam evidentiary force degrades with capability — above that threshold the instruments are the field itself (Bets, b).
- **tests**: exam run over the fixture corpus with FakeClaudeSession; evidence record schema; lapse trigger on degraded discrimination; re-exam on definition-hash change; each seeded class present.
- **files**: `pm_core/exams.py`, `pm_core/cli/exams.py`, fixture adapters over #160, `tests/test_exams.py`.
- **depends_on**: Calibration ledger hooks

### PR: Full convocation procedure — built at the trigger
- **description**: Implements the nine-step procedure once A3 has occurred: affected-set naming and expansion, positions as assent / objection / concern, fidelity challenges settled by reading, bounded termination with the loop guard and a per-node daily cap, sustain / override / absorb with embody-and-fork recorded as override, absorb graded on completion within a time box, the adjudication event, one-level escalation with refusals standing. Contested raises route here. Until this lands, the minimal contested path (Set A) escalates to the containing parent's approver.
- **tests**: convocation over a seeded contested change with three affected artifacts; fidelity challenge respawns; termination bound; cap enforcement; embody-and-fork logged as override; absorb completion grading; escalation re-hearing.
- **files**: `pm_core/watchers/convocation.py`, prompts, `tests/test_convocation.py`.
- **depends_on**: Plan-tree approval + escalation — the parent embodiment as approver (minimal contested path), Calibration ledger hooks

### PR: Scaffolding ablation ladder — does the infrastructure earn its place?
- **description**: The presumptuousness check: every layer of imposed structure is a *theorized* claim that it improves grounded outcomes for agents at current capability, tested by removal on the same oracle. Rungs, structure axis: **S0** — environment access only, mission "work on what you want"; **S1** — + the plan; **S2** — + technical infrastructure (containers, eval pipeline, ledger, dispatch); **S3** — + governance infrastructure (the full proposal). An orthogonal prompting axis runs from bare mission to full role/protocol prompting. Measured per rung: grounded outcome per unit compute, incident/crossing-violation rate, consent overhead, and *what structure the agents build themselves where none is provided* — S0 doubles as an expression-contact instrument and is where law 1 carries all the safety weight, stated honestly. Runs on [[plan-self-improve]]'s tournament machinery with the campaign as fitness. **Proven when**: rung deltas are measured across at least two capability tiers and at least one layer has been kept, cut, or made optional *because of* its measured delta.
- **tests**: rung harness launches reproducibly; per-rung metric collection; S0 emergent-structure capture; cross-tier report.
- **files**: `pm_core/ablation.py`, rung configs, tournament adapter, `tests/test_ablation.py`.
- **depends_on**: Governance benchmarking — seeded-bad-change exam harness

### PR: Multi-project digest (thin hierarchy)
- **description**: User-level registry of pm project paths (the roots the human follows plus any watch edges worth reading directly); `pm feed --all` merges their ledgers into one reading surface with provenance; the daily digest spans projects; anomalies and incidents first (R9). Purely the reading surface — structure between projects already exists in Set A.
- **tests**: registry; merged tail ordering; provenance tags; cross-project digest with anomalies first.
- **files**: `pm_core/feed.py` extension, user-config handling, `tests/test_feed_multi.py`.
- **depends_on**: Project feed v1 — append-only event ledger + digest

## The proving campaign (sister project)

**riscv-pareto** — an always-running energy-performance Pareto front for open-source RISC-V cores under a full-physical open-PDK eval — lives in its own sister project with its own pm instance and plan: `../riscv-pareto/pm/plans/plan-campaign.md`. Chosen because its acceptance check is a **measurement contract** that is fully mechanical: a merge is right iff the certified eval independently re-executes within tolerance and the front moves at root. (What re-execution proves is that the estimator repeats — not that routed-netlist power predicts silicon, which is the FPGA track's job, nor that the DUT boundary is fair, which is a root-adopted contract. Both are stated in the campaign plan.)

**The contract pm must satisfy (all Set A, checked by the launch manifest):**
- problem-source contract with outcomes (`not_worthwhile` flows back to the gap analyzer)
- `pm sub create` / `pm sub raise` / `pm plan register --parent`
- subprojects + promotion PRs (`base_branch`; streams as branch-rooted subprojects; core forks as separate-repo subprojects; the human adopts only at the root base)
- approver config + process registry + merge authority (parent-agent adoption in subtrees; eval-verify as certified process #1 with its acceptance flow frozen against the streams it grades; T1/T2 on grants)
- node work logs + maintained summaries (the onboarding projection every stream keeps current; verification loop later)
- crossing-request queue (upstreaming, publishing, new external deps, runner admission and quota changes)
- feed external events + digests (front deltas in the human's reading surface, anomalies first)

Set B's exam harness later earns its sign-off process the T3 (RTL-change) grant; Set B's drills are the campaign's first R7 instrument. **Citation update owed at M0**: the campaign plan cites laws by the old numbering (law 1 embodiment → Protocol v0 Embodiment; law 3 plural membership → thesis + Subprojects III; law 5 substrate → law 1); the same commit updates them.

## Open questions (pm-side)

- Code-voice summoning: when it enters (campaign T3 wanting "the ALU testifies"), does it reuse the [[plan-ff4f1a7]] question/response queue as the objection data model?
- Approver context: how much of the feed/history does minimal-sufficient-context give it per decision, and how is that measured?
- Reading across the DAG: one merged digest over every reachable project vs. per-root digests — and what the digest elides once dozens of feeds exist (R4 constrains the answer).
- The human's budget (R9): what is the bound — minutes per day, touches per week — and what happens when the feed exceeds it? (Probably: delegated grants pause at the boundary rather than the human skimming.)
- Absorb's time box: what default, and who files the miss when it lapses?

## Relationship to other plans

- `../riscv-pareto/pm/plans/plan-campaign.md` — the sister project; the external, from-scratch proving campaign Set A unblocks.
- [[watchers]] — *the always-on watcher framework (session health, supervisors, decision points).* Its supervisors (#144) + session health (#184) are Set A landing deps; the trust-prompt PR here delivers its pr-b53bfe2.
- [[plan-regression]] — *the autonomous regression/bug-fix loop; Phase 11 (sign-off + plan auto-start watcher) closes unattended auto-run.* The substrate this plan layers on; pr-ff9b728 and pr-ed10ac4 are Set A's first PRs in practice. Phase 10 + the bridge are non-dependencies.
- [[plan-momentum]] — *credible next-step surfacing, engagement disqualified.* Its law governs feed ranking when ranking arrives (R4).
- [[plan-radar]] — *auditable external-content triage.* The environment-contact organ; its own feed stays separate; its hand-tuned decay is the precedent for hand-built envelopes.
- [[plan-ff4f1a7]] — *adversarial doc review with a persistent question/response queue.* The future objection data model.
- [[plan-consult]] — *learned consultation routing, no capability hierarchy.* The standing instrument for the with/without value of human guidance; a human crossing is a future `consult(human)`.
- [[plan-self-improve]] — *the recursive pm tournament.* Home of the exam/tournament machinery Set B extends; the campaign is a natural target.
- [[plan-cb4ef69]] — *hierarchical plans.* This plan consumes its primitives and adds agent-initiated registration + subprojects; the rich UX stays there.
- [[plan-collaboration]] — *cross-user collaboration substrate.* Its Track F is this plan's deferred request filtering; Track D is worked example D.
- [[plan-mind]] — *the typed mind substrate.* Not a dependency; the feed folds into its EmissionLog later; its Budget is law 1's compute knob.
- [[plan-memory]] — *grounded recall.* The later upgrade to embodiment state; not a launch dependency.
- [[plan-984dfeb]] — *living artifacts.* The limit where artifact and intelligence fuse; v0's spawn-on-demand embodiments are the governance-side approximation.

**Related work (convergent, not borrowed).** The design was derived from the project's own substrate and converges with the 2026 agent-governance moment — CSA's AARM (action mediation, intent-aware policy), IMDA's voluntary agentic framework, NIST's agent-standards initiative, and vendor action-mediation specs. What is different here: adoption in place of permission, artifact-anchored objections, sustain/override/absorb, governance amended through its own exercised machinery, and the consent/substrate separation. The panel reviews (`pm/docs/adversarial-review/PANEL_*JURISDICTION*`) hold the fact-checked incident record this thesis reads from.

## Appendix: referenced PRs and subsystems — one-line summaries (state at 2026-09-02)

- **#225 / pr-2d5f712 (merged)** — the sign-off step: dedicated window, `sign_off` lifecycle status, verdict router; recommends `ready_to_merge`, never merges.
- **#226 / pr-8e693f6 (in review)** — sign-off UI: per-PR BDD report + dashboard; the human's adoption surface.
- **pr-ff9b728 (pending)** — plan auto-start watcher: one watcher per plan — picks ready PRs, caps in-flight, acts on sign-off recommendations per plan config, mutates the plan, keeps plan notes. **Set A's gate.**
- **pr-ed10ac4 (pending)** — no-progress safety stop across review/QA loops.
- **pr-fbda1a8 (pending)** — the bridge: Phase 10+11 integration checkpoint. Non-dependency.
- **pr-b53bfe2 (pending in `bugs`; relocated here)** — trust-prompt handling; context-aware verify-then-accept, never a bypass.
- **#184 / pr-18ac983 (in review)** — session-health watcher.
- **#144 / pr-871dbf5 (qa)** — high-effort watcher supervisors.
- **#160 (in review)** — review/QA regression benchmark suite; Set B's exam seed.
- **#161 (qa)** — container memory governor.
- **#121 (merged)** — QA PASS auto-merges only when auto-start is enabled; subsumed by pr-ff9b728's per-plan config.
- **#150 / #151 (merged)** — plan `parent` field + `## Plans` parser.
- **#153 / #200 (merged)** — base-branch hygiene: `pr start` refuses a PR not committed on the base; auto-commits the entry.
- **#164 / #120 / #122 / #124 (merged)** — container substrate: Podman, per-scenario isolation, tooling, branch-scoped push.
- **#139 / #138 (merged), #140 (in review)** — per-session-type model targeting + local/OpenAI-compatible providers.
- **#125 / #116 / #127 (merged)** — spec step; QA step with review↔QA loop; `pm pr qa`.
- **#132 / #174 / #178 (merged)** — watcher framework core; discovery supervisor; one-command activation.
- **#222 / #219 (in review)** — merge-path bugs: stash corruption; GitHub-backend conflict resolution.
- **#210 (in review)** — web server skeleton + SSE dashboard: optional feed base.
- **FakeClaudeSession (#148) / FakeGitHubBackend (#208) (merged)** — deterministic loop testing.
- **Phase 10 (plan-regression, pending)** — regressions-as-scenarios. Non-dependency.
- **Phase 11 (plan-regression)** — #225 + #226 + pr-ff9b728 (+ deferred pr-8015c1d). The substrate of this plan's adoption machinery.
- **mind + sensorium refactor** — in flight; deliberately not a dependency of anything here.
