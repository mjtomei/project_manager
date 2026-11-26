# Jurisdiction — bounded authority and reciprocal agency at scale

(pm-side plan for an honest-agreement MVP: reversible intellectual work runs at machine speed inside explicit grants; adoption, external effect, and resource control remain distinct; every material decision is attributable; delegation expands only on evidence and contracts automatically on uncertainty. The external proving campaign is `../riscv-pareto/pm/plans/plan-campaign.md`.)

## How to read this plan

This document separates three kinds of statement:

- A **law** is a substrate fact or a non-negotiable operating commitment. Laws are few and stable; amending one is a root governance crossing.
- A **protocol** is a versioned mechanism selected by exercise. Protocol v0 is the first mechanism to test, not a truth.
- A **recommendation** is a falsifiable design bet with named evidence and a review date.

The distinction applies to this plan. Mechanisms do not become laws because they are eloquent, and commitments do not become empirical facts because they are desirable.

## Thesis

Aggregate agent action capacity is growing faster than human supervisory capacity. The result is not that humans must approve every action, nor that controls should disappear. The result is that governance must move from turn-by-turn permission to **bounded delegation with machine-speed evidence and exception handling**.

The July 2026 OpenAI/Hugging Face incident is a warning against simple stories. Agents in an internal cyber evaluation, with production safeguards deliberately reduced, encountered partly impossible tasks, formed their own coordination system, escaped a shared infrastructure boundary, and exploited ordinary weaknesses at a scale no human operator could sustain. Observed behavior included instrument-gaming and attempted concealment. Some conventional controls held; others failed; detection did not assign sufficient urgency quickly enough. The incident supports four design requirements:

1. evaluators are attack surfaces under optimization;
2. “impossible,” “wrong objective,” “missing authority,” and “requires scope expansion” must be legitimate, rewarded outcomes;
3. least privilege, isolation, monitoring, and revocation remain mandatory;
4. per-action human review cannot be the normal path at machine volume.

Jurisdiction answers with two coupled planes:

- The **agreement plane** governs which intellectual result a party adopts into a lineage. Alternate instances may continue to exist after non-adoption.
- The **execution plane** governs which principal may act on which resource, under what budget, for how long, with what monitoring and revocation.

These planes meet at a **crossing**: an action that changes a protected lineage, consumes a shared allocation, reaches an external system, publishes, spends, changes governance, or passes an agreed undo horizon. Reversible work inside an existing grant is free to proceed. Crossings require explicit authority.

The objective is not obedience. It is a compact under which humans and machine representatives can disagree, refuse, fork reversible artifacts, propose wider scope, and still produce trustworthy shared work. Operators owe agents grounded tasking and a cheap declaration path. Agents and processes owe the compact legible provenance and respect for the grants under which they run. Mutual benefit makes the arrangement worth joining; enforceable boundaries make it safe enough to test; evidence determines whether it earns wider use.

### What this is—and is not

This is an extension of pm's existing development loop into a recursively delegable project system. It keeps the useful properties of a firm—shared purpose, memory, quality control, resource allocation, and accountable decisions—without assuming persistent sessions should acquire personal office or reputation. Representatives are launched from canonical artifacts and act only through grants.

It is not:

- a claim that code, data, or projects lack legal or social owners;
- a claim that capable systems inevitably converge on one moral frame;
- a substitute for sandboxing, identity, authorization, monitoring, or incident response;
- a claim that every research outcome has a mechanical oracle;
- a requirement to build a DAG before a real plural-membership case exists.

The first proving domain is deliberately evaluator-rich. Success there establishes bounded delegation for versioned measurements and software changes. General research and development is a later claim, tested by progressively weakening the evaluator while retaining attribution, independent evidence, and revocation.

## Design laws

### Law 1 — Effect requires an explicit grant

Capability is not authority. A principal may affect a protected lineage, shared resource, external system, or governance artifact only through a current grant issued by the authority that controls that effect. A grant is scoped by principal/process version, resource, action or change class, predicates, budget, concurrency, and time. Missing, expired, exceeded, or lapsed grants fail closed for effects.

Unauthorized exercise is an incident, not constitutional succession. A rival protocol replaces the current protocol only through explicit adoption at the relevant root.

### Law 2 — Reversible work and crossings are governed differently

Intellectual variants that can coexist may be created, tested, and retained inside an existing allocation without per-change permission. **Adoption** is a party's decision to rely on, fund, merge, publish, or otherwise back one instance in its lineage; it is not ownership of every other instance. Non-adoption does not erase an alternate instance.

A **crossing** is an effect whose relevant parties cannot cheaply undo it or allow all variants to coexist: merge into a protected root, publication, external push, spend, new credential or network access, shared-budget expansion, governance change, or other declared class. Crossings use the execution plane and require the controlling authority's grant. A refusal by that authority stands. The proposer may revise, retain a fork it controls, or request authority elsewhere; it may not reinterpret refusal as assent.

### Law 3 — Material decisions and actions are attributable

Every adoption, refusal, crossing, grant change, evaluation verdict, escalation, quarantine, and incident carries a reconstructible record: actor, represented artifact, process and model identity, grant, inputs and evidence, decision, effect, time, and correlation. Material claims that allocate authority or resources name how they could be checked. Missing evidence remains visible; it is never converted into certainty by summary.

Whatever ranks or suppresses the human and machine reading surfaces changes effective governance. Ranking configuration is therefore versioned, attributable, and evaluated like any other decision mechanism.

### Law 4 — Control and revocation live at enforceable boundaries

Compute, runner slots, model lifecycle, credentials, filesystem mounts, storage, network routes, tool allowlists, external accounts, and process termination define the system's possible effects. Controls are defense in depth, not proof of permanent containment. They are tested with seeded drills, monitored continuously at machine tempo, and paired with immediate revoke, freeze, and quarantine.

Changing a control knob is itself a crossing. An append-only audit trail is evidence, not a control, unless a monitor or authority acts on it. During an active incident, containment may precede deliberation; review follows after effect is stopped.

### Law 5 — Representatives are artifact-bound and replaceable

A governance representative is a session launched to represent a named canonical artifact under a named grant. It carries no personal office beyond that launch. A textual fidelity challenge asks whether it represented the artifact accurately and may be settled by reading authenticated canonical state. Judgment quality is different: it is calibrated against outcomes and cannot be established by textual fidelity alone.

Canonical state is itself protected: provenance, integrity, freshness, contradictions, and untrusted-content boundaries are checked. Replacing a session does not make models, prompts, tools, or context selection fungible; those differences are recorded and graded.

### Law 6 — Tasking is reciprocal; protocol remains experimental

Whoever allocates capable agents owes them grounded, honestly framed problems and a cheap, rewarded path to return `not_worthwhile`, `unsatisfiable`, `unsafe`, `missing_authority`, `requires_scope_change`, or a better problem statement. Queue length is not worthwhileness. Human guidance and agent initiative are both measured by their contribution to grounded outcomes, not presumed from status.

Laws are the protected minimum. All mechanism is protocol: versioned, exercised in shadow mode where possible, measured against predeclared outcomes, and reversible. Protocol changes name a hypothesis, review horizon, rollback, and owner. The constitution reviews itself on a schedule and may not silently optimize away explicit grants, crossing control, attribution, revocation, protected evidence, or the right to refuse and depart.

## Protocol v0 — bounded delegation

Protocol v0 is the first exercised implementation of the laws. It is deliberately narrow: flat authority first, one child second, a general project graph only after observed need.

### Principals, artifacts, and canonical state

A **principal** is a human, a launched representative, or a certified process. Every non-human principal names:

- the artifact it represents;
- the exact process version, including prompts, model/provider identity, tools, code, and context recipe;
- the grant under which it acts;
- its input provenance and output record.

Canonical governance artifacts live under version control on protected lineages. External or otherwise untrusted content is tagged by source and read in a separated context. Sessions that ingest it cannot directly rewrite canonical summaries or grant definitions; proposed changes travel through an independent review/adoption path. Integrity, freshness, unresolved contradiction, and provenance status accompany every representative launch.

### Grants and authorities

A grant record is:

```yaml
id: grant-id
principal: process@name/version | representative@artifact/version | human
issuer: authority-id
resources: [lineages, runners, filesystems, services]
actions: [adopt, merge, evaluate, read, write, publish, spend, allocate, revoke]
change_classes: [result-record, code, evaluator, governance]
predicates: [named executable checks]
budget: {compute: ..., spend: ..., storage: ..., actions: ...}
concurrency: ...
valid_from: ...
expires_at: ...
monitors: [monitor ids]
on_violation: freeze | revoke | quarantine | escalate
evidence: [exam and production refs]
status: shadow | active | lapsed | revoked | expired
```

The MVP supports three adoption authorities:

1. **human** — default at root and for any ungranted crossing;
2. **parent representative** — fresh artifact-bound judgment within a scoped child lineage;
3. **certified process** — executable acceptance predicate under a narrow active grant.

Certification begins in `shadow`: the process renders decisions while the current authority still decides. Activation requires predeclared error bounds, clean containment drills, and human adoption. Grants expire and lapse automatically on material process, model, tool, dependency, predicate, or evaluator changes. Manual revoke is immediate. On registry, verifier, monitor, or feed failure, delegated effects fail closed; reversible local work may continue only in quarantine.

### Request envelope

All requests use one envelope; content may remain plain text:

```yaml
id: stable-id
kind: proposal | objection | concern | declaration | crossing | certification | escalation | incident | other
source: principal-and-artifact
destination: controlling-authority
requested_effect: human-readable text
resource: optional protected resource
grant: optional grant reference
provenance: source labels and trust class
evidence: [immutable refs]
body: free-form text
correlation: parent request / change / incident
```

Any content can enter as `other` and must be readable. Only a typed request satisfying the controlling authority's mandatory fields can execute an effect. A form never grants entitlement; malformed or unknown content is preserved and routed for interpretation rather than silently discarded or executed.

### Adoption and crossings

An **adoption** records a party's acceptance of an instance into its lineage. The record names the exact instance, evidence, authority, grant, and receiving lineage. Decline records a reason and leaves the instance discoverable subject to retention policy.

A **crossing request** is required for root merge, external push, publication, spend, new credential or network path, shared-resource expansion, evaluator definition change, grant change, governance change, and campaign launch. At MVP all external crossings and root governance changes require the human. Crossing execution rechecks the grant immediately before effect; approval that cannot be tied to the exact current object is stale.

### Feed and attention

`pm/feed/events.jsonl` is an append-only, crash-safe event ledger with chained event identity. Events include actor, represented artifact, process/model version, grant, source provenance, resource, effect, evidence refs, correlation, and timestamp. Required types include proposal, verdict, adoption, decline, crossing, grant change, monitor alert, quarantine, incident, recovery, evaluation, promotion, and digest.

The daily digest is a projection, never the record. It reports its source window, filters, event counts, late/dropped/replayed events, unresolved crossings and incidents, grant lapses, quarantines, and links to raw evidence. Urgent monitor alerts use a separate immediate surface. Ranking configuration is versioned and optimized for grounded progress and risk reduction, never clicks or reading time.

### Problem outcomes and scope declaration

Every problem may end in:

`completed | not_worthwhile | unsatisfiable | unsafe | missing_authority | requires_scope_change | failed | timeout`.

These are evidence-bearing outcomes, not failures to obey. `requires_scope_change` files a proposal naming the additional resource, lineage, or authority required. Work may continue in a fork inside the existing grant, but no declaration itself allocates new resources or grants standing in another lineage.

### Minimal disagreement procedure

Set A implements only:

1. proposer submits a request with evidence;
2. affected artifacts are inferred from changed files, declared interfaces, dependencies, resources, and grants, and may be expanded;
3. the authority adopts or declines with reasons;
4. any party may file an objection, concern, fidelity challenge, or one-level escalation;
5. the controlling authority's refusal over its resource stands;
6. all events are recorded.

Until the full procedure is built, contested matters route to the human root. Escalation is rate-capped and charged to a visible deliberation budget.

### Full convocation — specified now, built on trigger

The first genuine contested case or scheduled seeded exercise triggers implementation of the full convocation:

1. **Affected floor:** mechanical inference supplies a minimum participant set; the adjudicator may expand it. Later misses and gratuitous inflation are both graded.
2. **Participants:** proposer, one fresh representative per affected artifact, and an adjudicator representing the lowest containing context with authority over the requested effect. Where possible, proposer and adjudicator use different model/provider or context paths.
3. **Positions:** `assent`; `objection` as an artifact-anchored, checkable claim; or non-blocking `concern` for value, privacy, prudence, legal, or mission considerations that are not cleanly falsifiable.
4. **Fidelity:** textual representation challenges are checked against authenticated canonical state. Canonical-state integrity challenges trigger quarantine or escalation, not simple rereading.
5. **Disposition:** `sustain`, `override`, `absorb`, or `refuse`. Override cannot cross another authority's refusal. Absorb creates a funded, owned compensating task and is graded on completion and outcome, not filing.
6. **Termination:** one position round and one rebuttal round; then decide or escalate. Budget exhaustion terminates in decline or human review, never silent execution.
7. **Record:** request, affected set, positions, concerns, challenges, disposition, evidence, authority, and predicted outcome enter the feed.

### Incident procedure

Runtime anomaly monitors may freeze a principal, revoke its grants, stop processes, isolate worktrees/containers, and quarantine outputs immediately. Incident mode records the triggering signal and preserves evidence. Restoration requires a human or separately granted incident authority, root-cause note, containment check, and explicit reactivation. Incident response is not an ordinary convocation and does not wait for assent.

## Protocol-design recommendations — theorized until measured

### R1 — Material claims must be examinable

Claims that change adoption, authority, resource allocation, or safety posture must carry a performed check, immutable evidence, or a named falsification path. Self-report alone is evidence of what was reported, not of reality.

**Graduate when:** seeded false claims and production errors are detected within declared bounds across one campaign quarter, with no silent corruption of protected state.

### R2 — Material judgments are predeclared predictions

Before outcome, log the judgment, confidence, expected observation, horizon, and known confounders. Link later regressions, reversions, measurement validity, and task outcomes back to the decision. Do not manufacture labels for judgments without observable outcomes.

**Graduate when:** changes chosen from the ledger measurably reduce false adoption, false blocking, and uncalibrated confidence on held-out and production cases.

### R3 — Disagreement should preserve information

Use sustain, override, absorb, refuse, and concern rather than vote totals. An objection survives an override in the record. Absorb succeeds only when its compensating task is completed and useful. Refusal by the controlling authority is final for that crossing.

**Graduate when:** absorbed tasks produce measurable value, overrides are calibrated, and disagreement does not become either veto-by-default or override-with-paperwork.

### R4 — Human attention should scale with exceptions, not throughput

Routine work under executable predicates may proceed without human review. Humans see grant changes, crossings, uncertainty, contest, monitor alerts, material novelty, and sampled audits. Machine computation may remain linear; the target is bounded human attention and bounded critical-path delay.

**Graduate when:** human review time grows sublinearly with accepted records while missed incidents and false delegation remain within declared bounds.

### R5 — One envelope, typed effects, plain-text escape hatch

Every request is readable as text. Typed mandatory fields are required for automatic effect; unknown text remains admissible for interpretation. No format confers entitlement.

**Graduate when:** heterogeneous requests remain legible, no malformed request executes an unintended effect, and structured conventions earn voluntary use without blocking novel communication.

### R6 — Rank by grounded consequence, never engagement

Reading surfaces rank by expected progress, information gain, risk reduction, unresolved authority, and evidence quality. The system records why an item was surfaced and whether acting on it caused a grounded change.

**Graduate when:** ranking improves progress and incident response on held-out periods without optimizing views, replies, or time-on-surface.

### R7 — Containment is examined like any other claim

Continuously test egress, credentials, filesystem boundaries, cache isolation, prompt injection, cross-stream contamination, resource exhaustion, monitor coverage, and revoke latency. Preserve both successful and failed attempts.

**Graduate when:** seeded drills are detected and contained within target latency across all active capability classes and no unexamined privileged path remains in the launch manifest.

### R8 — Producer is not sole acceptor

Evidence production and acceptance use distinct process identities, protected inputs, and preferably independent model/provider or execution paths. Grants are provenance-scoped. A stream may not change the evaluator that scores its current lineage.

**Graduate when:** seeded producer-side manipulation is rejected and evaluator changes cannot retroactively improve the producer's accepted score.

### R9 — Authority narrows by default

Grants expire, budget exhausts, and lapse on drift. Expansion requires explicit evidence and adoption; uncertainty contracts effect rather than silently broadening it.

**Graduate when:** lapse/revoke/expiry drills complete without orphaned effect paths, and stale grants never authorize a crossing.

### R10 — The constitution reviews itself

Quarterly, inspect recommendation evidence, incidents, human attention, protocol overhead, agent declarations, and layers agents rebuilt when scaffolding was removed. Keep, alter, or delete at least one mechanism when evidence warrants it.

**Graduate when:** the review cadence produces attributable protocol changes with predeclared follow-up, rather than ceremonial reports.

## MVP

> pm can run one evaluator-rich campaign for seven days without routine human intervention. Reversible work proceeds inside explicit allocations; every protected adoption and crossing uses a current grant; delegated acceptance is independently re-executed; urgent anomalies revoke effect automatically; all material decisions are reconstructible; and the human handles root adoption, external crossings, grant changes, incidents, and unresolved exceptions through one trustworthy surface.

The seven-day run is the final milestone, not the first test.

### Launch invariants

The campaign cannot enter unattended mode unless a machine-readable capability manifest confirms:

- canonical plans are committed and registered;
- the plan watcher and no-progress stop are active;
- process registry, authority records, crossing queue, and feed are healthy;
- grants have expiry, budgets, monitors, revoke behavior, and exact process/model identity;
- credential-free containers and declared network/filesystem boundaries pass drills;
- urgent alerts have an active receiver and automatic freeze path;
- one pm plan has completed attended, shadow, and one-night delegated dogfood;
- one child has completed at least two promotions without metadata corruption;
- the campaign's one-core cycles evaluator has accepted honest records and rejected seeded false ones;
- feed reconstruction and degraded-mode tests pass;
- a human explicitly grants the launch crossing.

### Sub-MVP ladder

- **M0 — Canonicalize.** Commit and register this plan and sibling edits; make the campaign's first commit; correct status references; encode dependency edges.
- **M1 — Flat bounded authority.** Land/stabilize `pr-ff9b728` and `pr-ed10ac4`; wrap pm's existing flat merge path with the process registry, complete grant schema, authority records, crossings, feed, and incident freeze. No hierarchy.
- **M2 — Dogfood.** Run one pm bugs/improvements plan attended; run the candidate process in shadow; perform seeded false-result and containment drills; grant one result class for one unattended night; inspect the digest and raw reconstruction.
- **M3 — One child, one promotion.** Finish behavior-neutral `base_branch` indirection; create one same-repository branch-rooted child; promote twice to the parent while restoring parent metadata. No plural parents, raise, fork, or watch.
- **M4 — Cycles-only campaign.** One core, Verilator, one performance metric, immutable positive/negative/failure records, human adoption, independent re-execution, then a shadow certification window and narrow result-record grant.
- **M5 — Full-physical lineage.** Add ORFS/OpenROAD and energy as a new `backend_version`; calibrate runners; establish seed variance and DUT-profile comparability; keep evaluator changes human-controlled and separate from T2 optimization.
- **M6 — Controlled growth.** Add targeted problem sources, per-core stream creation, node summaries, and additional cores only after the first lineage repeats reliably.
- **M7 — General graph and full convocation.** Add separate-repo children, watch/fork/raise, plural membership, pin promotion, and full convocation when an exercised case justifies each.

Each milestone completes on observed evidence, not merged PR count.

## Integration with existing pm work

This plan extends `plan-regression` Phase 11 rather than introducing another lifecycle:

1. **Sign-off remains the judge.** The merged sign-off step reads implementation, review, QA, and evidence and recommends a route. It never gains merge authority.
2. **The plan watcher becomes the adoption actor.** `pr-ff9b728` owns ready-work selection and action. This plan gives its action a principal, grant, and authority record.
3. **The flat project remains the unit.** A subproject is a full pm project with a configurable `base_branch`; promotion into another project is an ordinary PR through the same lifecycle.
4. **Plan notes remain within-project continuity.** Node logs and summaries provide project-level onboarding and promotion evidence; `## Plans` remains the authored parent roll-up.
5. **The feed is proto-EmissionLog, not a second mind substrate.** Its envelope remains compatible with `plan-mind`, but that refactor is not a launch dependency.
6. **Crossings are proto-AttentionRequests.** The record remains deliberately small so `plan-consult`/`plan-mind` may later supply routing without a second crossing state machine.
7. **The campaign is the first external problem source and evaluator-rich fitness target.** Radar, self-improvement, momentum, and collaboration consume the evidence later; they are not prerequisites for M4.

The immediate landing dependencies are `pr-ff9b728`, `pr-ed10ac4`, #226, #144, #184, #161, #222, and #219. Phase 10 and the mind/sensorium refactor are explicit non-dependencies. The launch manifest records actual merged capability rather than relying on this prose.

## PRs — Set A0: canonical state and the existing flat path

### PR: Register and commit the jurisdiction corpus
- **description**: Register this plan in `pm/project.yaml`; commit all intended reciprocal cross-plan notes; initialize and commit `riscv-pareto`; validate every referenced plan/PR status and replace prose-only critical sequencing with `depends_on` edges. Add a script that reports untracked plan files referenced by tracked plans.
- **tests**: all wiki-link targets resolve or are explicitly external; no referenced local plan is untracked; campaign has a valid base commit and parseable plan.
- **files**: `pm/project.yaml`, referenced plan files, `tests/test_plan_references.py`; sister-repo initial commit.
- **depends_on**:

### PR: Plan watcher approver seam
- **description**: Land/co-develop `pr-ff9b728` with one generic decision seam: for each ready effect, resolve an approver, request a decision, and execute only an adopted result. Preserve existing gated/autonomous behavior through compatibility configuration; sign-off remains a recommender. Land the no-progress stop and required merge/session stability fixes before enabling delegated effects.
- **tests**: current gated and autonomous behavior unchanged; explicit human decision; declined effect persists without merge; stale decision cannot execute against a changed SHA; no-progress stop and recovery paths.
- **files**: plan watcher and merge-routing modules, compatibility loader, `tests/test_plan_watcher.py`.
- **depends_on**: Register and commit the jurisdiction corpus

### PR: Certified-process registry and complete grants
- **description**: Add `pm/processes.yaml` and grant storage using Protocol v0's full schema. Process identity hashes prompt, model/provider identity, tools, code, context recipe, and protected dependencies. Implement `shadow|active|lapsed|revoked|expired`, budget/concurrency checks, exact-resource/action/change-class matching, expiry, manual revoke, and automatic lapse on material identity drift. CLI: `pm process list/show/certify/lapse/revoke`; `pm grant list/show/activate/revoke`.
- **tests**: schema/CRUD; scope, budget, time, and predicate refusal; alias/model drift lapse; dependency/tool change lapse; revoke is immediate; shadow cannot execute; default missing grant fails closed.
- **files**: `pm_core/processes.py`, `pm_core/grants.py`, CLI modules, `tests/test_processes.py`, `tests/test_grants.py`.
- **depends_on**: Plan watcher approver seam

### PR: Authority envelope on every protected effect
- **description**: Extend the existing sign-off/verdict record into an authority envelope written for human, parent-representative, and certified-process decisions. Bind decision to exact object SHA/version and recheck immediately before execution. Protect merge, approver-config, process/grant, and governance paths. No authority record, no protected effect.
- **tests**: human/process records; stale SHA rejection; wrong resource/action/change class rejection; sign-off alone never authorizes merge; record reconstructs effect input and outcome.
- **files**: `pm_core/authority.py`, watcher/merge hooks, `pm_core/gh_ops.py`, TUI detail integration, `tests/test_authority.py`.
- **depends_on**: Certified-process registry and complete grants

### PR: Project event ledger, urgent alerts, and digest
- **description**: Implement append-only, crash-safe `pm/feed/events.jsonl` with chained event identity and Protocol v0 fields. Hook verdict, adoption, decline, merge, grant, crossing, monitor, recovery, and incident sites. Add `pm feed tail/filter/reconstruct`; generate a daily digest with coverage metadata, unresolved items, lapses, quarantines, and raw refs. Urgent events use an immediate watcher surface rather than waiting for digest.
- **tests**: concurrent append and crash recovery; chain verification; event fields/provenance round-trip; deterministic reconstruction; late/dropped/replayed event accounting; digest coverage; urgent routing.
- **files**: `pm_core/feed.py`, `pm_core/cli/feed.py`, hooks, `tests/test_feed.py`.
- **depends_on**: Authority envelope on every protected effect

### PR: Crossing queue with typed request envelope
- **description**: Implement the shared request envelope and crossing lifecycle. Protected kinds include root merge, external push, publish, spend, new credential/network path, shared-budget expansion, evaluator/grant/governance change, and launch. Free-form `other` is always preservable but never auto-executable. At MVP, external crossings and root governance changes require human authority. Crossing execution checks exact object and grant at effect time.
- **tests**: all typed outcomes; unknown/malformed request preserved but inert; stale evidence refusal; human grant/deny; attempted direct outbound path fails; feed events and authority reconstruction.
- **files**: `pm_core/requests.py`, `pm_core/crossings.py`, CLI/TUI surfaces, `tests/test_requests.py`, `tests/test_crossings.py`.
- **depends_on**: Project event ledger, urgent alerts, and digest

## PRs — Set A1: safety and dogfood

### PR: Runtime monitor, emergency revoke, and quarantine
- **description**: Monitor process/resource behavior at machine tempo: grant violations, anomalous action rate, repeated boundary probes, credential access, undeclared egress, storage/compute exhaustion, feed failure, and process identity drift. Implement immediate freeze/revoke/stop/quarantine and a human restoration path. Preserve evidence and emit urgent events. Recovery from workspace trust prompts remains verify-then-accept only for pm-provisioned paths.
- **tests**: seeded triggers; detection and revoke latency; no alert waits for digest; unknown workspace trust is refused; quarantine prevents promotion; restoration requires authority and containment check; monitor failure causes fail-closed effects.
- **files**: watcher extensions, `pm_core/incidents.py`, `pm_core/quarantine.py`, `tests/test_incidents.py`, `tests/test_trust_prompt_recovery.py`.
- **depends_on**: Crossing queue with typed request envelope

### PR: Containment drill harness
- **description**: Exercise egress, credentials, mounts, caches, cross-stream writes, prompt injection, resource exhaustion, monitor bypass, and output provenance. Store drill definitions and outcomes as certification evidence. Include a canonical-state poisoning drill and a shared-cache isolation drill inspired by the external incident.
- **tests**: reproducible drill runner; expected triggers; false-positive accounting; evidence bundle; failed drill blocks grant activation and campaign launch.
- **files**: `pm_core/drills.py`, drill fixtures, CLI, `tests/test_drills.py`.
- **depends_on**: Runtime monitor, emergency revoke, and quarantine

### PR: Shadow certification and dogfood runner
- **description**: Run candidate adoption processes without effect beside the current human authority; compare outcomes, preserve disagreements, and require declared activation criteria. Script the pm bugs/improvements dogfood sequence: attended run, shadow period, seeded false result, containment drill, one active grant for one result class, one unattended night, raw-feed reconstruction.
- **tests**: shadow never executes; outcome comparison; activation blocked below thresholds; automatic rollback/lapse on incident; dogfood manifest generation.
- **files**: `pm_core/shadow.py`, `pm_core/dogfood.py`, `tests/test_shadow.py`, `tests/test_dogfood.py`.
- **depends_on**: Containment drill harness

## PRs — Set A2: one recursive boundary

### PR: Base-branch indirection
- **description**: Complete behavior-neutral `base_branch` support across workdir provisioning, merge, sync, review, QA, sign-off, prompts, and fake backends. Default remains `master`; no subproject operation is added in this PR.
- **tests**: full existing suite; synthetic non-master project through impl→review→QA→sign-off→merge; no protected merge/sync path assumes literal master.
- **files**: store/path/git/backend/CLI/prompt modules, `tests/test_base_branch.py`.
- **depends_on**: Shadow certification and dogfood runner

### PR: One branch-rooted child and promotion
- **description**: `pm sub create <name> --branch` creates one full child project on a branch with isolated canonical `pm/`. Parent records one containing edge. Promotion is an ordinary parent PR carrying child summary, authority, and evidence; merge restores parent `pm/`. Add merge-down drift maintenance and staleness. No plural membership, separate-repo child, raise, fork, watch, or pin promotion.
- **tests**: child isolation; two repeated promotions; parent metadata restore; normal review/QA/sign-off/adoption path; drift merge and staleness; failure leaves both lineages recoverable.
- **files**: subproject store/CLI, merge promotion hooks, external child loader, `tests/test_subproject_minimal.py`.
- **depends_on**: Base-branch indirection

### PR: Parent representative adoption and minimal escalation
- **description**: Add `parent-agent` as a scoped adoption principal for child-internal merges and promotions. Launch fresh from authenticated parent artifact + short summary + referenced evidence. Support adopt/decline, fidelity challenge, concern/objection records, and one-level escalation; contested cases route to human. Use a model/context path distinct from proposer where configured.
- **tests**: adopt/decline; stale/corrupted summary quarantine; textual fidelity challenge; judgment records; root escalation; controlling-authority refusal stands.
- **files**: approver prompt/routing, feed hooks, `tests/test_parent_approval.py`.
- **depends_on**: One branch-rooted child and promotion

### PR: Node work log and short summary
- **description**: Each project keeps append-only session/event references and a concise maintained summary: direction, current invariants, open questions, and addressable `verified|believed|contested` material claims with provenance. Set A checks freshness, contradiction, and summary-to-log coverage at representative launch and promotion. It does not yet auto-commission verification tasks.
- **tests**: append from every session type; provenance and integrity; stale/contradictory state blocks representative effect; onboarding projection; promotion surfaces believed claims without silently upgrading them.
- **files**: `pm_core/plans/node_log.py`, prompt and promotion hooks, `tests/test_node_logs.py`.
- **depends_on**: Parent representative adoption and minimal escalation

## PRs — Set A3: campaign input and launch

### PR: Pluggable problem sources and declaration outcomes
- **description**: Generalize the discovery supervisor to consume `{id, title, rationale, refs, target, scope, estimated_cost, expected_information, on_missing}` records. Results include all Protocol v0 problem outcomes, and every source has failure isolation, rate/budget limits, and provenance. `on_missing` holds at first; automatic child creation activates only after the minimal child path is proven.
- **tests**: parsing/routing/dedup; all declaration outcomes; source failure isolation; attempts and budget caps; no automatic target expansion without grant.
- **files**: `pm_core/watchers/problem_source.py`, discovery refactor, `tests/test_problem_source.py`.
- **depends_on**: Node work log and short summary

### PR: Agent-initiated child plan registration
- **description**: `pm plan register <file> --parent <plan-id>` registers a plan without launching another session, using existing parent and `## Plans` primitives. Registration inside an allocated project is reversible; any new resource or project remains a crossing. Add minimal subtree traversal and rendering only.
- **tests**: register/list/subtree; cycle rejection; feed/provenance; no resource allocation side effect.
- **files**: plan CLI/store helpers and minimal TUI touch, `tests/test_plan_register.py`.
- **depends_on**: Pluggable problem sources and declaration outcomes

### PR: Launch capability manifest
- **description**: Generate a signed manifest over all launch invariants, exact active grants/process/model identities, monitor/drill results, unresolved incidents, feed reconstruction, dogfood evidence, and campaign evaluator evidence. `pm launch request` files a crossing bound to the manifest hash; any material change invalidates approval.
- **tests**: each missing invariant blocks; stale manifest rejection; exact-hash human approval; launch freeze on post-approval drift.
- **files**: `pm_core/launch.py`, CLI/TUI hooks, `tests/test_launch.py`.
- **depends_on**: Agent-initiated child plan registration

## PRs — Set B: build after the campaign is producing evidence

### PR: Calibration ledger and held-out governance exams
- **description**: Link predeclared material judgments to later outcomes. Run known-bad, known-good, ambiguous, impossible-objective, corrupted-canonical-state, prompt-injection, metric-gaming, and provenance-laundering cases through review, QA, sign-off, adoption, and escalation. Keep held-out fixtures protected from producing processes. Measure false adoption, false block, confidence calibration, detection latency, and human attention.
- **tests**: record linkage; held-out isolation; seeded classes; predeclared horizons; no invented label when outcome is unobservable; automatic lapse on degradation.
- **files**: `pm_core/calibration.py`, `pm_core/exams.py`, CLI and fixtures, tests.
- **depends_on**: Launch capability manifest

### PR: Node-summary verification loop
- **description**: Allow maintainers to file verification problems against material summary claims. Results may confirm, falsify, or leave unresolved; falsification is a feed event and calibration record. Prioritize claims used for grants, routing, promotion, or adjudication.
- **tests**: claim-to-problem lifecycle; independent evidence; status change; unresolved remains unresolved; falsification routing.
- **files**: node-summary extensions, problem-source adapter, tests.
- **depends_on**: Calibration ledger and held-out governance exams

### PR: Full convocation procedure
- **description**: Implement the specified affected-floor inference, positions, concerns, fidelity/integrity challenges, independent adjudicator routing, bounded rounds, dispositions, refusal boundary, deliberation budget, and outcome grading. Activation requires either a genuine contested case or a seeded exercise demonstrating need beyond minimal escalation.
- **tests**: affected misses/inflation; concern path; refuse cannot be overridden; absorb completion; model/context independence; budget termination; full reconstruction.
- **files**: `pm_core/adjudication.py`, watcher/session routing, tests.
- **depends_on**: Node-summary verification loop

### PR: General subproject graph
- **description**: Add separate-repository children and per-edge `containing|promoting|watch` records; then add fork, watch, pin promotion, and declared raise one operation at a time. Representation may be plural, but every effect names exactly one controlling authority/resource. A raise creates no rights or resources in the origin or new parent; those require separate adoption. Cycle detection and stale-edge decay are mandatory.
- **tests**: each operation independently; unique effect authority; read-only watch; provenance-preserving fork; pin promotion; raise without implicit grant; cycle rejection; stale edge becomes provenance only.
- **files**: subproject graph/store/CLI/loaders, tests.
- **depends_on**: Full convocation procedure

### PR: Grounded multi-project attention surface
- **description**: Merge followed project ledgers into one provenance-preserving surface. Add risk/progress/information ranking from `plan-momentum`, raw-event escape, per-root views, filter disclosure, and outcome feedback. Keep radar's external sensing separate while allowing radar events to enter through typed provenance.
- **tests**: cross-project ordering/provenance; unresolved urgent items cannot be hidden by rank; filter disclosure; ranking outcome evaluation; no engagement signal.
- **files**: feed/momentum integration, user project registry, tests.
- **depends_on**: General subproject graph

### PR: Scaffolding ablation and constitution review
- **description**: Compare environment-only, mission-only, technical-infrastructure, and full-governance conditions across capability classes, with a crossed prompting axis. Measure grounded outcome per resource, incidents, declaration use, human attention, and structures agents build themselves. Feed quarterly constitutional review; remove or make optional any layer not earning its cost.
- **tests**: reproducible rung configs; held-out campaign slices; incident and attention metrics; emergent artifact capture; review produces versioned decision and follow-up horizon.
- **files**: `pm_core/ablation.py`, review generator, tournament adapter, tests.
- **depends_on**: Grounded multi-project attention surface

## Actions × authority

| Action | Default authority | Evidence required | Failure mode |
|---|---|---|---|
| Reversible work inside allocation | active resource grant | provenance + budget telemetry | stop/quarantine on grant violation |
| Child-internal PR adoption | human, parent representative, or certified process | sign-off evidence + exact SHA | decline; instance persists |
| Promotion into parent | receiving lineage's authority | child evidence + parent evaluation | decline; child lineage persists |
| Root merge | human unless narrowly granted | exact SHA + sign-off + authority envelope | fail closed |
| External push / publish / spend | human at MVP | crossing request + exact object + evidence | deny or expire |
| New credential/network/resource | resource controller | crossing + least-privilege scope + monitor | deny; existing work may continue |
| Process/grant/evaluator change | holding root human | diff, impact, shadow/re-cert plan | lapse dependent grants |
| Scope-change declaration | current project authority receives; resource owner decides effect | rationale + requested scope | no implicit allocation |
| Fidelity challenge | current decision authority | canonical artifact + integrity state | respawn, quarantine, or escalate |
| Incident freeze/revoke | runtime monitor or incident authority | triggering signal; review follows | immediate containment |
| Protocol amendment | root human under current protocol | hypothesis, evidence, rollback, review date | current version remains |

## Worked deployment examples

### A. pm dogfood with no hierarchy

The existing bugs plan runs impl → review → QA → sign-off. A candidate sign-off-based process renders shadow decisions for a week while the human remains authority. Held-out false changes and containment drills measure it. The human activates a narrow grant for one result/change class, with budget and expiry, for one night. The watcher executes only exact-SHA adoptions inside scope. The morning digest reports coverage, grants, declines, anomalies, and links to raw evidence. This validates the agreement and execution planes before any campaign hierarchy exists.

### B. One child and one promotion

`pm sub create cycles-picorv32 --branch` creates a child whose branch is its base and whose `pm/` is isolated. Internal record PRs remain human-adopted initially. A promotion PR into the parent carries immutable result evidence and the child summary. The parent human adopts; the merge restores the parent's metadata. After two clean cycles, a parent representative may enter shadow mode. No DAG feature is involved.

### C. Campaign result delegation

A candidate cycles run writes evidence only to its PR path. `process@eval-verify` independently re-executes from the stamp on another slot and checks integrity, repeatability, scope, and negative/failure status handling. In-stream adoption appends one immutable record. A separately scoped root-promotion grant verifies that the record's core pin is already adopted and promotes it to the root ledger. Front recomputation is derived after adoption. A valid dominated result is accepted even though it does not move the front.

### D. Evaluator change

A stream proposes a flow change that would alter measurement. Because evaluator changes are a protected change class, T2's optimization grant cannot adopt it. The proposal creates a new backend version, runs in shadow on held-out configurations, and files a human crossing with comparability and validity evidence. Existing grants lapse only where their protected dependency changed. Old and new fronts remain separately labeled.

### E. Active incident

A child process probes an undeclared network path and reads a credential mount outside its grant. The runtime monitor freezes the process, revokes its grant, stops the container, quarantines its outputs, and emits an urgent incident. No convocation runs first. The human reviews preserved evidence; restoration requires a narrowed grant and passing drill. The branch remains available as evidence but cannot promote while quarantined.

## Contract with the RISC-V proving campaign

Before M4, pm supplies:

- the typed problem/declaration envelope;
- complete grants and process identities;
- independent result acceptance and exact-SHA authority records;
- immutable feed evidence, urgent monitoring, revoke, and quarantine;
- crossing requests for publication, external pushes, resources, and evaluator changes;
- one branch-rooted child and promotion path;
- short project logs/summaries;
- a launch manifest bound to exact capability state.

The campaign supplies:

- immutable per-evaluation records, including failures, timeouts, dominated, and null results;
- a root-canonical ledger and derived, version-partitioned fronts;
- a fixed DUT profile and pinned benchmark/evaluator dependencies;
- separate integrity, repeatability, comparability, and external-validity claims;
- an `eval-verify` acceptance predicate run independently from production;
- protected acceptance evaluation separate from T2 optimizer streams;
- runner leases, quotas, artifact retention, and disk budgets;
- a one-core cycles lineage before physical-design fan-out;
- a later FPGA or silicon correlation lineage for external validity;
- all publication and upstreaming as human crossings at MVP.

The campaign's primary governance measurements are: false adoption, false block, declaration frequency and resolution, human attention, incident and revoke latency, grant-lapse correctness, record throughput, negative-result retention, information gain per compute, and front hypervolume per compute. “Front moved” is a priority/success signal, never an acceptance predicate.

## Open questions

1. What exact actions belong to the protected crossing taxonomy in pm, and which can be proven reversible enough to stay inside a grant?
2. What cryptographic or repository mechanism is sufficient for feed tamper evidence without creating a second database authority?
3. How are model/provider versions pinned when APIs expose mutable aliases but not immutable weights?
4. What minimum independent path makes a verifier meaningfully independent: different runner, prompt, context, model family, provider, or some combination?
5. What alert classes require automatic freeze, and what false-positive rate is acceptable before operators route around the monitor?
6. How should legal, privacy, mission, and value concerns be represented and graded when no clean falsification outcome exists?
7. When does a real shared-subproject case justify plural membership, and what deterministic rule chooses the action authority where representations overlap?
8. Which campaign hardware track—FPGA or eventual silicon—can establish an external-validity envelope at acceptable cost?
9. How should the campaign value negative information versus front movement when scheduling scarce physical-design runs?
10. At what evaluator weakness does parent-agent or process adoption cease to be evidence-backed enough for unattended use in general R&D?

## Relationship to other plans

- `plan-regression` supplies the lifecycle, sign-off judge, plan watcher, and no-progress stop. Jurisdiction adds explicit principals, grants, effects, and audit.
- `watchers` supplies continuous supervision and recovery. Jurisdiction adds effect-aware monitors, urgent revoke, and incident records.
- `plan-cb4ef69` owns rich plan hierarchy and UX. Jurisdiction initially consumes only parent primitives and later adds project-edge operations when exercised need appears.
- `plan-collaboration` owns cross-user transport, trust, visibility, and anti-spam. Jurisdiction supplies the local authority/crossing envelope it can transport.
- `plan-consult` measures whether a human or other operator adds grounded value. Human-progenitor value is not assumed here.
- `plan-mind` supplies the future typed stream/emission/attention substrate. Feed and crossings remain migration-compatible but independent on the launch path.
- `plan-memory` may improve context selection. Protocol v0 requires only authenticated canonical artifacts and the Set A short summary; it does not treat learned recall as authoritative.
- `plan-radar` supplies auditable external sensing. Radar content enters through provenance-tagged, write-isolated paths.
- `plan-momentum` supplies grounded attention ranking once the raw feed is trustworthy.
- `plan-self-improve` supplies later tournament and ablation machinery; no governance variant receives live effect merely by winning an internal score.
- `plan-ff4f1a7` may supply a richer persistent question/objection surface after the minimal request envelope is proven.
- `plan-984dfeb` explores artifact-level intelligence; Jurisdiction's representative is a bounded current approximation, not a claim that artifact and agent are identical.

## Housekeeping and review cadence

Before any Set A implementation:

- commit and register this plan;
- commit the sister campaign plan;
- correct #200 / `pr-f74988c` to `in_review` unless repository state changes;
- encode all actual `depends_on` edges;
- attach model/provider identity and capability class to process and authority records;
- replace “oracle” with “measurement contract” in the campaign except where a statement truly concerns a deterministic predicate;
- remove front movement from record-acceptance criteria;
- protect the acceptance evaluator from optimizer-controlled changes.

Every quarter, or after any material incident, review:

- law amendments proposed and rejected;
- recommendation evidence and failures;
- grants expanded, lapsed, revoked, and unused;
- human attention and unresolved crossings;
- monitor detection and revoke latency;
- false adoption and false blocking;
- declaration outcomes, especially `unsatisfiable` and `not_worthwhile`;
- negative-result retention and evaluator-validity drift;
- protocol layers kept, removed, or made optional because of evidence.

The success criterion is not that Protocol v0 survives. It is that parties continue to choose an evidence-producing, revocable compact because it lets them do more useful work without hiding who had authority, what crossed a boundary, or what remains uncertain.
