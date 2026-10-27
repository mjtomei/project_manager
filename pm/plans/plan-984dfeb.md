# Living artifacts: data + intelligence as the unit

**The organizing idea: treat everything we can afford to as a living thing —
data and intelligence fused into a single unit — and ask what happens.**

Today's plan and PR markdown files are static snapshots. More broadly: today
in computing, data is passive (rows, records, files, code) and intelligence
is separate (scripts, models, humans, agents). The two are bolted together
by orchestration code that watches one and modifies the other. This plan
makes the opposite move: the *unit itself* carries both. Every artifact in
the system has its own content **and** its own intelligence — wants,
negotiation capacity, self-maintenance, integrity concerns. Orchestration
isn't an external layer; it's what emerges when units of this kind interact.

This is the headline. Everything else in the plan — replacing pm's plan
files, replacing PR specs, replacing pm's own state, the stretch study of
code-as-artifact — is an *instance* of the headline. The instances are
how we learn what's possible when this is the substrate. Further instances
beyond what's enumerated below are expected and welcome.

Previous formal systems for negotiating tasks (actor systems, contract-net,
blackboard architectures) gestured at this but were boxed in by determinism
and programmability constraints. They had to make the intelligence part
small and rigid; the unit's "agency" was barely more than a scheduling
hint. General intelligence in every unit removes that ceiling. Tasks and
the connections between them can grow organically. We study the prior work
for inspiration and vocabulary, not as a blueprint.

The deeper claim: **the human stops being a bottleneck and becomes a
boundary.** When the units of a system are alive and can negotiate among
themselves, work proceeds in parallel without routing through a single
observer. The human interface stops being the place where every decision
is made and becomes the surface where desires from units that couldn't
be auto-resolved get raised. Most work never reaches the human; what does
is the work where human judgment adds something the negotiation couldn't
produce on its own.

## What the artifact looks like

An artifact is a structured object (not just markdown prose) consumed primarily
by LLMs. Its state includes:

- The document content itself (what plan files contain today).
- A live task queue: pending, specializing, executing, blocked, completed,
  rejected.
- Negotiation history: which tasks have proposed to run in parallel, preempt,
  or merge with which other tasks, and the outcomes.
- Self-maintenance schedule: artifact-spawned tasks that keep the document
  coherent, up to date, or otherwise healthy.
- Rejection rationale: when the artifact (or another task) rejects a task,
  why.

The shape is "data structure for LLM consumption" — high-bandwidth, more
expressive than a markdown file, but still text-renderable so humans can audit
and intervene.

## Tasks as the atom — proposals in motion, not finished edits

The fundamental unit is the task, not the edit. A task carries a proposal that
is *alive* — continuously evolving in response to negotiation with other
tasks, the artifact's integrity constraints, and (sometimes) human input.
Proposals don't become edits until they've negotiated themselves into a
shape that fits among the other in-flight work. There is no point in time
when "the edit is being reviewed" — proposals exist in superposition across
many tasks simultaneously, converging as they negotiate.

This is why earlier formal systems for task negotiation feel adjacent but
limiting: they treated the task's output as fixed and negotiated over
scheduling. Here the task's content itself is the negotiation surface.

A task moves through phases (entry → specialization → in-flight →
landed/folded/dropped) but each phase is a property of the live task, not a
queue position:

- **Entry**: arrives as a generic request for a modification to the artifact.
  No type yet, no prompt scaffold yet.
- **Specialization**: the artifact's type narrows the available operation
  classes; the task takes on one, picking up the prompt scaffold and
  vocabulary that operation class implies.
- **In-flight**: the task is alive — proposing, counter-proposing,
  responding to other tasks' proposals, possibly executing partial work
  in shared workdirs, possibly pausing. Multiple in-flight tasks can act
  on overlapping regions of the artifact simultaneously.
- **Landed / folded / dropped**: the task's proposal has converged enough
  to commit (landed); has been absorbed into another task's proposal
  (folded); or has lost coherence with the artifact and dissipated
  (dropped). These are descriptions of trajectory, not adjudications.

## No central arbiter

There is no single manager-intelligence that observes the whole artifact
and adjudicates conflicts. Tasks negotiate peer-to-peer; parallel changes
to the artifact take place; conflicts resolve with **artifact integrity as
a constraint** that each task is accountable to, not as a rule enforced
from above.

The constraint is concrete: each task can see (and is asked to consider)
the artifact's integrity-relevant context — what other proposals are in
flight nearby, what the artifact's self-maintenance has been concerned
with recently, what shape the document would have if this proposal landed.
A proposal that visibly degrades integrity is one that other tasks (and
the artifact's own maintenance tasks) will push back on during negotiation
— not because an arbiter rejected it, but because no negotiated shape that
preserves integrity could absorb it.

Humans enter the system at a single point of contact per prompt or task,
but the artifact as a whole is not meant to fit in any one observer's
head at once. Humans see, like everyone else, a local slice — enough to
participate in one task's negotiation. Composition across slices happens
in the artifact itself.

## Privileged participants — not arbiters

"No central arbiter" doesn't mean "all participants are equally weighted."
Humans and watchers are **privileged participants**: when they engage with
a negotiation, their voice carries more weight than peer tasks'; their
proposals are harder for other tasks to push back on; their concerns about
integrity have more force. Crucially, they're still participants, not
observers — they don't sit above the negotiation watching every move.
They show up where they show up, and shape what's nearby; the rest of
the artifact runs without them.

This layering is what makes cost stratification possible later. Once the
prototype works with uniformly capable tasks (full-strength LLM per task),
we can demote routine specializations to cheaper intelligence — because
the privileged participants are the safety net. A cheap task that drifts
into incoherence gets pushed back by an integrity-maintenance task, by a
watcher's higher-weight counter-proposal, or by a human's intervention
when they happen to be nearby. There's no need for every task to be
capable enough to self-arbitrate, only capable enough to negotiate.

The privilege gradient (rough sketch, to refine in early PRs):

- **Humans** — highest weight where they engage, but engagement is sparse.
- **Watchers** — high weight, scoped to the domain they watch (a TUI watcher
  has more authority over TUI-shaped negotiations than over plan-coherence
  negotiations).
- **Self-maintenance tasks** — moderate weight, scoped to the artifact's
  own integrity concerns.
- **Regular tasks** — baseline weight. Can be staffed by cheap or expensive
  intelligence depending on the operation class.

## Wants — artifacts as anthropomorphized peers

The artifact-as-peer framing only has teeth if the artifact has its own
**wants**. Self-maintenance tasks aren't generated by abstract scheduling
rules — they're generated by asking, of each artifact: *if this artifact
were alive and wanted the higher-level structure it lives in to improve,
what would it want done?* The answer becomes one or more in-flight tasks
that the artifact then negotiates alongside everyone else's tasks. Wants
are how the artifact participates as a peer rather than as a passive
substrate.

The anthropomorphization is intentional and operational. It's not a
metaphor for the user's benefit; it's a prompt scaffold that shapes how
LLM tasks reason about what each artifact should do. A plan artifact
"wants" its PRs to remain coherent with its overall motivation; a PR
artifact "wants" its spec to stay consistent with the work happening
in its workdir; a code artifact "wants" its callers to use it in ways
that match its actual cost profile. These aren't preferences a human
authored — they're what an artifact of that kind, if alive and
oriented toward improving its surrounding structure, would care about.

**Want-inference should itself be automated.** Early in the plan we'll
likely scaffold wants by hand per artifact type (each type comes with a
prompt that asks "what would an artifact of this type want for the
higher structure"). Later, a dedicated task class observes the artifact
and synthesizes wants automatically — closing the loop and removing the
last place a human had to hard-code per-artifact judgment.

## The artifact's own tasks

The artifact periodically spawns self-maintenance tasks (coherence
checks, summary regeneration, stale-content sweeps, integrity-pressure
notifications to nearby in-flight tasks). These tasks are concrete
expressions of the artifact's wants — they're what the want-inference
described above produces. They're first-class tasks that negotiate
alongside the human/agent-spawned ones. This is what makes the artifact
appear alive: it isn't a snapshot waiting to be edited, it's a
substrate with its own ongoing concerns, surfaced as work.

## Scope and sequencing

**First milestone: plan files become living artifacts.** Replace the current
plan-markdown-plus-project-yaml-entry split with a richer artifact that
contains the document, the task queue, and the negotiation surface. Keep the
human-readable markdown view as a rendering of the underlying artifact, so
humans can still read and edit by hand.

**Later milestone: PRs become living artifacts of the same kind.** Once the
plan-as-artifact pattern is proven, fold PR entries into the same model. The
PR's "spec" becomes the document, the impl/review/QA/merge flow becomes tasks
in the queue, and what pm currently does as orchestration becomes negotiation
inside the artifact.

**Eventual milestone: pm's orchestration is the artifact protocol.** All of
pm's current flows (start, review, QA, merge, watchers, sync) become specific
task types over the artifact substrate. pm itself becomes a renderer and a
host for the artifacts, not a state machine.

## Where this leads — instances we expect to follow

The PRs enumerated below are the instances we're committing to in this plan
(pm's plans, then pm's PRs, then pm itself, then a stretch study on
autonomous program optimization). Once the substrate is real, other instances
become available — each one a new domain where the data+intelligence unit
might unlock something previously bottlenecked by external orchestration:

- **New shapes of evolutionary algorithms.** Classical evolutionary
  algorithms operate on passive genomes with an external fitness function
  and an external selection mechanism. When each candidate is itself alive
  — capable of evaluating its own fitness in context, proposing changes to
  itself, and negotiating with neighbors — selection emerges from the same
  integrity-pressure and negotiation dynamics that drive everything else
  in this plan. This isn't classical EA with smarter genomes; it's a
  qualitatively different mode where the population is a community of
  living units, not a population of strings.
- **Self-organizing knowledge bases.** Notes, references, summaries, and
  derived facts as living units that maintain their own connections, surface
  staleness, and negotiate consolidation when overlap is detected.
- **Self-tuning infrastructure.** Configuration values, deployed services,
  monitoring rules as living units that observe their own efficacy and
  negotiate with each other to converge on operationally sensible
  configurations without a human operator in the loop.
- **Living research workflows.** Hypotheses, experiments, and result
  artifacts that reason about their own status and surface to the
  researcher when consensus among them breaks down.

These aren't on the critical path for this plan — they're directions the
substrate makes possible. The plan's job is to build the substrate well
enough that any of these (or things we haven't thought of) can be
attempted as a follow-on with low friction.

## Open questions to explore in early PRs

- What is the artifact's persistent representation? Markdown + sidecar JSON?
  A single structured file (YAML/TOML/custom) that renders to markdown? A
  small SQLite? CRDT-friendly for concurrent in-flight task state?
- How does the live state of in-flight tasks persist across pm restarts —
  not as queue position, but as the actual evolving content of each task?
- What does negotiation look like in practice — what does a task *see* when
  it's prompted to respond to another task's proposal, and what is it
  expected to return? Free-form, or a small set of shapes (PARALLEL_OK,
  COUNTER_PROPOSAL, ABSORB_INTO_MINE) with prose attached?
- How is **artifact integrity** made legible to a task — as a checklist,
  as the artifact's own voice (a self-maintenance task that participates
  in the negotiation), as a learned-from-examples norm, or as something
  else? Integrity has to be a thing tasks can be *accountable to* without
  a central enforcer.
- What happens when negotiations don't converge on their own — does
  pressure from integrity-focused maintenance tasks reshape proposals,
  do stalled negotiations time out into "dropped," or does the artifact
  itself surface the impasse to a human as a single-point-of-contact
  prompt? Probably some combination, but no central manager.
- Privileged participants — humans, watchers, self-maintenance tasks —
  carry more negotiation weight than baseline tasks. How is "weight"
  made concrete in the prompts that drive peer tasks? Is it a numeric
  field a task reads, a structural difference in how privileged proposals
  are presented, or learned-from-examples? Whatever the form, it has to
  be legible enough that a cheap-intelligence task can defer correctly.
- What's the routing rule for cost-tier assignment? Some operation classes
  (boilerplate edits, well-bounded reformats) should clearly run on
  cheap intelligence; others (cross-section coherence, novel proposals)
  clearly should not. We'll want this to be data-driven, not hard-coded.
- What's the minimum prior work to absorb before designing? (Actor model,
  contract-net, blackboard, Engelbart's NLS, Bret Victor / Dynamicland,
  MemGPT, recent LLM-OS framings.) The framing is inspiration-only —
  those systems were boxed in by determinism and programmability
  constraints, and most of them assumed a central scheduler or arbiter.
  General intelligence in every task, and integrity-as-shared-constraint
  rather than integrity-as-enforcement, are the unlocks here.

## Out of scope (for this plan)

- Migrating away from text-files-in-git as the durable backing store. The
  artifact representation may augment the file layout, but the source of
  truth stays text-and-git-able.
- Replacing tmux/Claude-session orchestration. Task execution can still
  happen in panes and Claude sessions; this plan is about the substrate
  those tasks act on, not the execution mechanism.

## PRs

### PR: Prior-work survey and design vocabulary
- **description**: A short writeup (2–4 pages) synthesizing what's worth borrowing from each of actor model, contract-net, blackboard systems, Linda tuple spaces, Engelbart NLS, Bret Victor / Dynamicland, CRDTs/OT, MemGPT, AutoGen group chat, Karpathy's LLM-OS framing, and other relevant references. For each: the negotiation/coordination primitive it offers, the constraint that limited it historically, and how generally intelligent tasks change the picture. Produces the shared vocabulary subsequent PRs use. Inspiration-not-blueprint framing.
- **tests**: Writeup is reviewable and concise; each reference contributes a named primitive or vocabulary term used in later PRs.
- **files**: pm/plans/artifacts/prior-work.md (new)
- **depends_on**:

---

### PR: Artifact schema sketch — concrete proposal for plan artifacts
- **description**: Concrete schema (not prose) for a plan artifact: document body, task queue with lifecycle states, negotiation history, self-maintenance schedule, rejection log. Decide representation (markdown + sidecar JSON vs. single structured file vs. SQLite) with tradeoffs argued. Output: a real example artifact for an existing plan in this project, rendered both in structured form and as a human-readable markdown view.
- **tests**: Round-trip a real plan through the proposed schema. Human-readable view matches the structured-form source. Schema validates with a small linter.
- **files**: pm/plans/artifacts/schema.md (new), prototype schema definition under pm_core/artifacts/ (new)
- **depends_on**: Prior-work survey and design vocabulary

---

### PR: Negotiation protocol — peer-to-peer, integrity-as-constraint
- **description**: Define how in-flight tasks see and respond to each other. No central arbiter — each task's prompt scaffold includes (a) the artifact's integrity-relevant context, (b) other in-flight proposals nearby, (c) recent self-maintenance concerns. Output shapes that emerge as worth naming (PARALLEL_OK, COUNTER_PROPOSAL, ABSORB_INTO_MINE, DISSIPATE, and others from the survey PR) — each defined as what a task sees and what it returns. Phase transitions (entry → specialization → in-flight → landed/folded/dropped) are described as trajectories, not adjudications. Walk through three concrete scenarios: a self-maintenance task running alongside an in-flight user task; two overlapping proposals converging into one (folded); an in-flight proposal that drifts away from integrity and dissipates without anyone "rejecting" it.
- **tests**: Each named shape demonstrated end-to-end in at least one scenario. Non-convergent case shown to resolve without a central decision — via integrity pressure, via folding, via dissipation, or via surfacing to a human at a single-point-of-contact prompt.
- **files**: pm/plans/artifacts/protocol.md (new)
- **depends_on**: Artifact schema sketch — concrete proposal for plan artifacts

---

### PR: Want-inference — anthropomorphized artifacts that surface their own desires
- **description**: Make the "what would this artifact want, if it were alive and wanted the higher structure to improve" question operational. First-pass scaffolding: per-artifact-type prompt scaffolds that, given the artifact's current state, produce a set of named wants — concrete things the artifact would want done — which become in-flight tasks negotiating alongside human/agent-spawned ones. The plan artifact wants its PRs coherent with its motivation; the PR artifact wants its spec consistent with workdir reality; etc. Each artifact type ships with a hand-authored "wants prompt" in this PR, and we observe whether the wants it generates feel right when surfaced as tasks. Future work (separate PR): automate the want-inference itself so artifacts don't need a hand-authored prompt per type.
- **tests**: For at least two artifact types (plan and one other), running the wants prompt against a real artifact produces plausible named wants. Each named want becomes an actual in-flight task that the protocol can negotiate. Wants are renderable in the markdown view so humans can audit what the artifact is asking for.
- **files**: pm_core/artifacts/wants.py (new), per-artifact wants-prompt files under pm_core/artifacts/wants/
- **depends_on**: Negotiation protocol — peer-to-peer, integrity-as-constraint

---

### PR: Single-plan prototype — replace one plan file with the artifact
- **description**: Pick one existing plan (small, e.g. this plan itself or another modest one) and replace its plan file with the living-artifact representation. Wire pm so the TUI can read the artifact and render its markdown view. Demonstrate at least one self-maintenance task firing (driven by the wants infrastructure from the previous PR) and one task-to-task negotiation. PR entries continue to use the legacy format — this PR is plan-side only.
- **tests**: TUI reads the artifact and renders correctly. At least one self-maintenance task fires automatically from the artifact's wants. At least one task-to-task negotiation completes (in either direction). Legacy plan files still parse alongside the new format during transition.
- **files**: pm_core/artifacts/, pm_core/tui/ (rendering integration), one migrated plan file under pm/plans/
- **depends_on**: Want-inference — anthropomorphized artifacts that surface their own desires

---

### PR: Extend to all plans, keep PRs legacy
- **description**: Migrate every plan file in this project to the artifact representation. PR entries remain legacy. Mostly migration plus shaking out edge cases (huge plans, plans with many tasks, plans that depend on other plans, external plans).
- **tests**: All plan files load and render correctly post-migration. No regression in plans pane / TUI / plan review. Edge cases (external plans, hierarchical parent plans) handled.
- **files**: pm/plans/ (all migrated), pm_core/artifacts/ (edge-case handling)
- **depends_on**: Single-plan prototype — replace one plan file with the artifact

---

### PR: Automated want-inference — remove the hand-authored wants prompt
- **description**: Replace the per-artifact-type hand-authored "wants prompt" from the want-inference PR with a dedicated task class that observes an artifact and synthesizes wants automatically. The task sees the artifact's current state, its history of in-flight tasks and their negotiations, and the surrounding artifacts it interacts with, and produces the same shape of named wants that the hand-authored prompt did — without per-type templates. Closes the loop on "intentional anthropomorphization is itself automated." After this PR, adding a new artifact type doesn't require authoring a new wants prompt; the inference task generalizes.
- **tests**: For each artifact type already migrated, the automated wants-inference produces wants that are at least as good as the hand-authored prompt produced (judged against a small evaluation set of artifacts where we know what wants we'd want). Adding a fresh, unseen artifact type produces sensible wants without any new hand-authored content.
- **files**: pm_core/artifacts/wants_inference.py (new), retirement of per-type wants prompts under pm_core/artifacts/wants/
- **depends_on**: Extend to all plans, keep PRs legacy

---

### PR: PR entries become artifacts of the same kind
- **description**: Fold PR entries into the same artifact model. The PR spec markdown becomes the document; impl/review/QA/merge work becomes tasks in the artifact queue. pm's existing orchestration paths (pr start / pr review / pr merge / watchers / sync) become task types that negotiate inside the PR artifact.
- **tests**: PR lifecycle (start → review → QA → merge) runs end-to-end through the artifact protocol on a real PR. Watchers and sync interact with PR artifacts via the same task primitives.
- **files**: pm_core/artifacts/, pm_core/cli/pr.py, pm_core/watcher_*.py, pm_core/pr_sync.py
- **depends_on**: Extend to all plans, keep PRs legacy

---

### PR: pm as artifact host, not state machine
- **description**: Refactor pm's remaining orchestration into the artifact protocol. pm becomes a renderer for artifacts and a host for tasks running against them; it no longer owns workflow state directly. Every piece of state pm currently tracks (project.yaml, plan files, PR specs, pane registry, watcher state) is either an artifact or a task acting on one.
- **tests**: project.yaml as today no longer holds workflow state; all flows expressible as artifact + tasks. Existing TUI/CLI surfaces still work. No regressions in the demo flows used elsewhere in this project.
- **files**: pm_core/ (broad refactor), pm_core/store.py (becomes thin), project.yaml migration
- **depends_on**: PR entries become artifacts of the same kind

---

### PR: Stretch study — code as living artifacts for autonomous program optimization
- **description**: Once the artifact substrate is proven for plans, PRs, and pm's own state, study whether the same framing can be applied to **code itself** — treating functions, modules, or other units of code as living artifacts that negotiate with each other to autonomously optimize a program. Research questions to investigate: do the same primitives (specialization, negotiation, integrity-as-constraint, self-maintenance) translate when the artifact is a piece of running code? What does "integrity" mean for code (correctness preservation, performance bounds, interface stability)? What does a self-maintenance task look like for code (profiling-driven hot-spot identification, refactor proposals, dead-code dissipation)? Can two code-artifacts negotiate a change to their shared interface? Does the system converge on optimization improvements without human intervention, and over what timescales? **Concrete scenario to drive the design:** code-artifact A observes (via its own self-maintenance task running over profiling data) that it spends most of its time on task X originating from artifact Y. A opens a negotiation directly with Y — not via a central optimizer — proposing alternatives like "send me X less often," "send X pre-aggregated," "let me cache X across calls," or "fold a piece of your work into me to avoid the round trip." Y, who has its own integrity concerns and its own in-flight tasks, counter-proposes or absorbs the request into its own self-maintenance. The optimization that results is whatever shape the two artifacts negotiate, not what a centralized profiler-plus-optimizer would have prescribed. **Upshot if it works:** this is a demonstration that optimization of an engineered system can proceed without the human as bottleneck. The system's pieces manage themselves in parallel; the human interface becomes a surfacing of desires from artifacts that couldn't be auto-resolved — not a control point every optimization has to route through. The negotiation infrastructure built earlier in this plan generalizes from "managing the work that builds the system" to "the system managing itself," with the human present at the boundary rather than along the critical path.

This is exploratory — produces a writeup with a small-scale demonstration (one program, a handful of code-artifacts, an autonomous optimization run with observable trajectory including at least the A-talks-to-Y scenario above) and a recommendation on whether the framing generalizes or hits limits specific to code-as-artifact.
- **tests**: Writeup includes a real autonomous-optimization session with observable task trajectories. At least one negotiated cross-artifact interface change is demonstrated. Limits and where-it-broke-down are documented with the same weight as where-it-worked.
- **files**: pm/plans/artifacts/code-optimization-study.md (new), small experimental harness under pm_core/artifacts/experiments/ (new)
- **depends_on**: pm as artifact host, not state machine
