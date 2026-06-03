# Collaboration — Cross-User Automated Collaboration as Substrate for an Open Meritocracy

(the future where every collection of resources runs intelligent-collaboration infrastructure, opens enough of its work to be reachable by other intelligences, and the ones that do outcompete the ones that don't — until what gets built is gated by the quality of contribution rather than by org-chart access)

## The primary motivation: open + intelligent-collaboration-capable outcompetes closed

A claim about where things are headed, and what infrastructure makes it possible:

Today, contribution to large projects is heavily gated by organizational boundaries. To meaningfully contribute to a project you usually need to be employed by it, invited into it, or operating within a narrow set of pre-defined channels (issues, PRs against a public repo). The bottleneck isn't the contribution's quality — it's the **attentiveness cost** the project bears to evaluate inbound work against its current state, and the **integration cost** of bringing accepted contributions into the project's working artifacts. Maintainer burnout in open-source is the visible symptom: attentiveness scales linearly with contributors, the maintainer scales not at all.

AI agents change both costs. With sufficient context about a project's current state, agents can — at scale, on a continuous basis — surface candidate contributions from outside that are actually relevant, summarize them in a form that fits the project's working artifacts, and prepare the integration. The radar (`[[plan-radar]]`) is the substrate inside one project; this plan extends the same substrate across projects.

If that holds, the projects that **open enough of their work to be reachable** by other intelligences get two massive force-multipliers: **development power** (contributions from many minds, not just employed ones) and **attentiveness** (find-and-manage capability that now scales with the agents watching, not with the maintainer). Projects that don't open enough lose access to both.

And there is a stronger version of the thesis worth naming: **large pools of resources that try to self-isolate quickly get starved of ideas and innovation; in the limit, once you have solved all your own problems, you have nothing left to do.** Any closed system's problem space is finite; new problems worth solving come from contact with other contexts. Isolation is self-terminating, not merely competitively disadvantaged — closed systems hit a natural growth ceiling regardless of what their competitors are doing. The organizations and projects that have understood this — that built strong open ecosystems around themselves precisely so they kept encountering new problems — are the ones that stayed productive over long horizons. The substrate this plan delivers makes that openness scale further than it ever has, because AI agents now do the attentiveness and integration work that previously gated how open an organization could afford to be.

The end state, if the substrate matures: contribution becomes a real meritocracy — what advances a project is the quality of work surfaced in the cross-project landscape, not the org chart that gates access to it.

**This plan delivers the substrate that makes that competition possible.** It does not claim the future will arrive on any timeline. It builds what would be needed if it does — and is useful immediately, at much smaller scale, to any single user who wants to collaborate across project boundaries today.

## What this plan is and isn't

- **Is:** cross-pm-project collaboration protocol + non-pm-user on-ramp via shadow projects + public-facing visibility / permissions model + the agent infrastructure to detect and manage cross-project collaboration + the trust / safety / quiet-defaults model that makes the system worth using.
- **Is not:** a specific platform's collaboration product (this is the substrate, not a competitor to GitHub or its peers); not a claim that this outcome is inevitable (the thesis is competitive; adoption is the question); not a guarantee that openness is the right strategy in every context (proprietary work for legitimate reasons remains proprietary; the choice stays the project owner's).
- **Goal voice of the system:** quiet. Agents work in the background to surface candidate cross-project collaborations; the human user decides whether to engage. The system never auto-contributes to another user's project without explicit per-action approval, and the default visibility on every artifact is `private`.

## Depends on

- **`[[plan-radar]]`** — external-overlap detection is a direct extension of the radar's source-and-triage machinery; the navigation primitive and Artifact primitive are reused wholesale. This plan's MVP cannot ship until radar's MVP does.
- **`[[plan-quality]]`** — the bug-finding-as-demo machinery (Track E) is what makes the on-ramp moment concrete for non-pm parties.
- **`[[plan-regression]]`** — the regression + auto-fix machinery is the other "ready-to-pick-up artifact" the on-ramp demonstrates.
- **`plan-cb4ef69`** (hierarchical plans) — useful when cross-project collaboration happens at the plan level rather than the PR level (shared dependencies across projects).

## v1 / MVP — minimum useful slice

Four PRs to land the smallest version that produces value:

1. **External-overlap detection strategy** (Track A) — a new radar strategy that surfaces candidate cross-project connections, not just candidate articles.
2. **Shadow-project bootstrap** (Track D) — given a public repo URL, create a pm project structure populated from the external party's artifacts.
3. **Demo via plan-radar** (Track E) — run the radar on a shadow project; produce the synthesis section as a ready-to-pick-up artifact.
4. **Quiet-defaults visibility tier** (Track F) — every pm artifact carries a visibility tier, defaulting to `private`; no exposure happens without explicit opt-in.

That MVP is the smallest version that demonstrates the thesis on one user / one external project: pm produces value for the external party first, the user decides whether to share, the external party (if shown) sees a deliverable rather than a pitch.

---

## Track A — External-overlap detection (extends `plan-radar` sourcing)

The radar's current sourcing strategies look outward for content. This track adds strategies that look outward for **overlap** with the user's own project state — open-source repos working on similar problems, public issue trackers with overlapping themes, blog posts whose author is solving a near-by problem. Output is candidate cross-project connections rather than candidate articles.

### PR: `external-overlap` strategy file

New strategy at `pm/radar/strategies/external-overlap.md`. Same shape as other strategies; output items carry an `external-overlap` tag and a structured `overlap_target` field naming the external project / repo / author. The agent picks queries by reading the user's current open plans / in-flight PRs / stated goals and searching for parties doing structurally similar work.

### PR: Triage agent extension for overlap candidates

The opening comment for an `external-overlap` item goes deeper than a generic article triage: it specifically compares (what the external party has done; what we've done; what each could borrow from the other). The feature-ideation step gains an additional kind: `collaboration-candidate` — paired work between projects, where the "target" names what each party would do and the "alignment" scores reflect both parties' stated goals.

---

## Track B — Public-facing project surface + visibility / permissions model

For a project to be reachable by other intelligences, some part of it must be public. Today pm artifacts are all effectively private (workdir + project.yaml + plan files on the user's machine). This track defines the public-facing surface and the model that gates it.

### PR: Visibility-tier field on every pm artifact

Plans, PRs, threads, notes, captures all gain a `visibility` field: `private` (default) / `share-on-request` / `public`. Editable by the user or via the preferences-chat surface. Schema-validated, audit-logged on change.

### PR: Public-facing surface generator

`pm publish` (or similar): static export of artifacts marked `public` to a configured path / git repo / S3 bucket / etc. Output includes plan titles + summaries, recent thread items above a relevance threshold, sign-off reports for merged PRs — whatever the user has opted into. Read-only for v1.

### PR: Inbound interaction model

Initially read-only: anyone with the URL can read public artifacts. Commenting and proposal flow come later (Tracks C and F). The point of v1 is reachability without exposure to spam or attack surface.

---

## Track C — Cross-pm-project collaboration protocol (both parties use pm)

When both parties run pm, a richer collaboration protocol becomes possible: artifact sync across projects, proposal flow via the Artifact primitive, conflict resolution when parallel work diverges.

### PR: Project-to-project artifact-sync protocol

Define the wire format and trust model. Shared threads land in both projects' radars; comments propagate (with provenance). Per-artifact opt-in: the user explicitly chooses which threads / plans / PRs sync to which peer projects.

### PR: Cross-project proposal flow

When the triage agent on project A surfaces a `collaboration-candidate` feature targeting project B, it can prepare a proposal that lands on project B's preferences-chat surface as a candidate edit. Project B's user reviews and accepts / rejects via the same preferences-chat / Artifact mechanism they use for their own preferences.

### PR: Conflict resolution

When two projects' parallel work diverges (e.g., both extending the same shared plan in incompatible directions), surface the conflict to both users, present the divergence as a structured choice (analog of git merge but at the artifact-graph level), let each user decide.

---

## Track D — Shadow projects + non-pm-user on-ramp

The collaboration flow should not require the other party to use pm. When the overlap-detection strategy identifies an external party doing materially relevant work, pm sets up a **shadow pm project** for them on the user's machine, populated from the external party's public artifacts, running the user's pm machinery against it.

### PR: Shadow-project bootstrap

Given a public repo URL (or set of URLs), create a pm project structure that maps the external party's artifacts to pm's data model — issues → bugs, files → plan candidates, README/docs → plan summaries, etc. Stored under `~/.pm/shadows/<external-id>/`, with provenance back to every source artifact.

### PR: Shadow-project maintenance

Keep the shadow in sync with upstream artifacts on a cadence; flag drift; surface significant upstream changes. The shadow grows alongside the external party's real work.

### PR: Shadow-project visibility boundary

What gets exposed to the external party at the on-ramp moment vs what stays on the user's machine. Default: nothing exposed until the user explicitly packages and shares. The shadow project's existence is private to the user until they decide otherwise.

---

## Track E — Demo flow (running existing pm machinery on shadow projects)

The on-ramp moment is when the external party sees that pm has been quietly producing value for their project — and decides to claim it. This track delivers the demos.

### PR: Run plan-radar on the shadow project

Produce a radar for the external party's project state. The synthesis section of the radar's summaries becomes a ready-to-pick-up resource-allocation candidate list for the external party's project, not the user's. The deliverable is a one-page HTML or markdown the external party can read in five minutes and immediately see value.

### PR: Run plan-regression + plan-quality machinery on the shadow project

Produce candidate bug fixes against the external party's code, complete with QA captures, sign-off reports, and the "before/after" reproductions. Present as a ready-to-pick-up artifact: here are N bugs we found, here are the proposed fixes, here is the evidence each one is real and fixed.

### PR: On-ramp packaging

When the user decides to share, package the shadow project's output as a single artifact — a draft PR (or set of PRs) against the external repo, plus an explanation document, plus a how-to for the external party to take over the shadow project themselves if they want to. The external party's first interaction is **reading a deliverable, not evaluating a pitch.** The on-ramp moment is when they decide to claim it.

---

## Track F — Trust / boundaries / safety

The collaboration substrate creates obvious risks: surveillance disguised as collaboration, intellectual property leakage, low-quality contributions overwhelming maintainers, automated harassment dressed up as proposals. This track addresses them concretely; the quiet-defaults PR is MVP.

### PR: Quiet defaults

Every visibility tier defaults to `private`. Every cross-project action defaults to gated rather than autonomous. Users explicitly choose what to open and to whom. The plan's posture is "share nothing until the user says otherwise."

### PR: User-set rate limits per external relationship

How many proposals an external party can submit; how often a shadow project's output is updated; how often pm auto-syncs an artifact. All configurable per relationship via the preferences-chat surface.

### PR: Audit logging

Every cross-project action is logged with full context (who, when, what, why, on whose authority); the user can review and reject historical actions. Trail is exportable.

### PR: Anti-spam

Proposals from a party whose past proposals have been rejected at a high rate get rate-limited automatically. Obvious low-effort proposals (e.g. content that fails the radar's own relevance threshold) are filtered before reaching the user. The maintainer-overwhelm failure mode of conventional open-source is what this PR specifically tries to prevent recurring at agent scale.

---

## Cross-mind substrate primitives (added during agent-wrapper refactor)

This section captures the typed primitives that make the rest of this plan implementable. They are what controls the layer through which different minds interact, and they compose with [[plan-mind]] (the mind) and [[plan-sensorium]] (the shared environment pm interacts with). The 4-PR migration sequence in the wrapper refactor lands this substrate in PR4 (or pre-PR1 if collaboration work starts during the refactor — decision deferred until then).

### Framing

Every individual user runs a **mind** — the collection of streams of consciousness operating on their project, defined in plan-mind. This plan's substrate is about how two minds interact when **they are separate entities with their own goals** — where the relationship is not "shared filesystem, collaborate freely" but "distinct projects with distinct priorities that may converge, diverge, or disagree."

Two reasons cross-mind interaction matters beyond what the ambient sensorium already supplies:

1. **Disagreements that can't be immediately resolved.** Two minds may have different priorities, different model of what's worth doing, or different interpretations of a shared artifact. They need a protocol for surfacing the disagreement, negotiating, and either reaching alignment or recording the split. Filesystem-mediated sharing has no semantics for this — git is a great substrate for "I edited X" but a poor one for "I think your X is wrong and here's why." The federation primitives below are what give minds language for that conversation.

2. **Scaling beyond what one project can manage.** When a task's complexity exceeds the coordination capacity of a single pm project, splitting into multiple projects becomes necessary. Compression between the components then takes shapes like public documentation, product releases, advertised stable interfaces, versioned dependencies, changelogs — the forms cross-project interaction has always taken. The federation primitives below are the typed substrate for that compression: minds publish stable channels other minds depend on; identity attestation lets the dependents know who is making the promises; visibility tiers govern what stays internal vs. exported.

A single pm project is sufficient when neither of these applies — when one team and one mind cover the work. This plan kicks in when the project either splits or interacts with parties whose goals are not aligned by default.

The cross-mind substrate primitives below are the typed layer for those cases. Plan-collaboration as a whole (the tracks above) describes the policies, on-ramps, trust model, and demos built on top of that substrate.

**Inherited primitives from [[plan-mind]] and [[plan-sensorium]]** — used below with no re-definition: `Artifact` (the on-disk shared mutable thing), `Payload`, `VisibilityTier` (with `Party(project_id)` parameterized variant), `CallbackRegistry`, `Mind`, `Stream`.

### Core principle: cross-mind interaction is sensorium-mediated, not message-passed

`Emission` is mind-internal. It does not cross mind boundaries. Two minds with separate goals **interact through the sensorium** — which mostly means the broader public sensorium (git, GitHub, the open web, published releases, public APIs, peripherals) that pm doesn't control. A mind publishes to the public substrate (commits to a public repo, ships a release, posts a paper, writes a blog post); the other mind reads from that substrate via its runtime's normal tools. This works today without any pm-specific transport, and it's what most cross-mind interaction will continue to be.

This plan's typed primitives cover the **narrow case** where two minds want **pm-specific guarantees** (typed schema, change-notify, ACL) on their shared Artifacts without relying on the public substrate. That's a small slice of cross-mind interaction. For everything else, the answer is: use the broader sensorium directly via the runtime's normal tools — no plan-collaboration primitives required.

The framing drops two primitives I'd have added under a message-passing model:

- **No `FederatedMailbox`.** There is no cross-mind Mailbox. Mailboxes route Emissions; Emissions stay inside a mind.
- **No `SignedEmission`.** Authentication is the transport's job (git commit signing, HTTPS TLS, or signed Artifact versions where stronger guarantees are needed). The wrapper does not introduce a cross-mind message envelope.

When this section's primitives ARE needed: when two pm projects want shared typed Artifacts with schema validation and change-notify across mind boundaries without committing every change to a public repo. When they AREN'T needed: when minds share via GitHub, the open web, or any other public sensorium piece — that already works without anything in this plan. The MVP of plan-collaboration (Tracks A–E) mostly uses the public sensorium; the typed primitives below are for Track C onward and for cases where the public substrate's looseness is a liability.

Cross-mind primitives (for the narrow typed case):

### 1. `ProjectIdentity` (Payload + service)

The local mind's identity in cross-project contexts. Used to attribute Artifact authorship, declare relationships, and (when needed) sign Artifact versions for transport.

```python
@dataclass
class ProjectIdentity(Payload):
    project_id: str                                 # globally unique, human-readable: 'matt/pm', 'org/repo'
    display_name: str
    signing_pubkey: PublicKey                       # half others use to verify Artifact versions we authored
    party_relationships: dict[str, PartyRelationship]   # project_id -> trust/visibility/transport config

@dataclass
class PartyRelationship:
    visibility: VisibilityTier                      # tier we publish to this party at
    redaction_rules: list[RedactionRule]            # per-party redaction overlays at the publish seam
    transport: 'TransportConfig'                    # how Artifact state syncs (git, https, tmux-socket)
    inbound_write_policy: Literal['accept', 'review', 'reject']    # what we do when this party writes to a shared Artifact

class IdentityService:
    def attribute(self, artifact: Artifact, version: int) -> ProjectIdentity  # who wrote this version (from transport metadata)
    def sign_version(self, artifact: Artifact, edit: Edit) -> bytes | None    # optional; default uses transport-level signing
    def verify_version(self, artifact: Artifact, version: int) -> bool        # checks transport-level + optional explicit sig
```

### 2. `PublishedArtifact` (decorator / mixin on `Artifact`)

An `Artifact` is published cross-mind when it has one or more parties in its publication set. Most Artifacts are local; published ones explicitly opt in.

```python
class Artifact:                                     # extends the base in plan-sensorium
    published_to: set[str] = field(default_factory=set)    # project_ids this artifact is published to
    publish_visibility: dict[str, VisibilityTier] = field(default_factory=dict)   # per-party tier override

    def publish_to_project(self, project_id: str, tier: VisibilityTier) -> None
    def unpublish(self, project_id: str) -> None
```

**Publication = readable by named project.** Setting `published_to = {'org/repo'}` with `publish_visibility['org/repo'] = VisibilityTier.public` means org/repo gets read access; org/repo's mind can mirror this Artifact via the transport. Writes from org/repo back to this Artifact are subject to the local `write_acl` PLUS the relationship's `inbound_write_policy`.

`apply()` on a published Artifact triggers transport sync to all `published_to` projects in addition to the local `artifact.<name>.changed` emission. The transport batches and delivers the new version to the receiving mind, which materializes it into its local sensorium as if a local edit had landed.

### 3. Cross-mind transport — Artifact synchronization, not message passing

The transport layer synchronizes Artifact state between minds whose sensoriums are not directly shared. It does NOT carry Emissions.

```python
class Transport(Protocol):
    """Synchronizes Artifact versions between two minds with separate sensoriums."""
    def publish(self, artifact: Artifact, edit: Edit, to: ProjectIdentity) -> PublishReceipt
    def fetch(self, from_project: str, artifact_name: str, since_version: int) -> list[Edit]
    def subscribe(self, from_project: str, artifact_glob: str, handler: Callable[[Edit], None]) -> SubId
    def authenticated_as(self) -> ProjectIdentity   # what identity the transport is operating under
```

Concrete transports (each implements the same Protocol; the cross-mind layer doesn't care which):

- **`pm_core/collaboration/transport/git.py`** — git-backed. Publication = commit + push to a configured remote; fetch = pull. Transport-level auth via commit signatures + push permissions. No infrastructure dependency. Async by nature. The default.
- **`pm_core/collaboration/transport/https.py`** — HTTPS push/pull against a small relay or peer-to-peer endpoint. Lower-latency for live channels. Auth via mutual TLS or signed bearer tokens.
- **`pm_core/collaboration/transport/tmux_socket.py`** — same-host multi-user shared tmux socket (pm already has `SHARED_SOCKET_DIR` + Unix-group permissions). Useful for pair-style local collaboration where two minds run on one machine.

A `Mind` subscribes to remote Artifact changes via:

```python
mind.callbacks.on(
    'artifact.<name>.changed',
    from_project='org/repo',                        # NEW: filter by remote project_id; absent = local only
    handler=on_remote_spec_update,
)
```

Under the hood the transport delivers the remote `Edit` to the local sensorium, which `apply()`s it into a mirrored local Artifact. The Stream that subscribed sees the change as if it were a local edit — the artifact-change abstraction is uniform across "local edit," "remote edit synced via git pull," and "remote edit pushed via HTTPS." Transport choice is policy, not semantics.

### 4. Cross-boundary visibility enforcement

Uses the `VisibilityTier` field defined on Artifacts (plan-sensorium) and Emissions (plan-mind). For Artifacts:

- `visibility=private` — never published; cannot be cross-mind even if `publish_to_project()` is called.
- `visibility=user_internal` — same as private for cross-mind purposes (user-internal is "private but shareable across this user's own projects").
- `visibility=Party(project_id)` — published only to that party.
- `visibility=public` — publishable to any party in `published_to`.

The transport refuses to publish an Artifact whose visibility is below the recipient party's authorized tier. This is the structural backing for the quiet-defaults invariant — an Artifact emitting at the wrong tier cannot exfiltrate by accident.

For Emissions, the within-mind enforcement (defined in plan-mind) is sufficient — Emissions don't cross mind boundaries at all.

### 5. Cross-boundary redaction at the publish seam

`RedactionPolicy` (defined in plan-sensorium as a write-time filter) gets per-party overlays at the publish seam. When `apply()` syncs an Artifact version to project B, the transport applies:

- The local mind's base `RedactionPolicy`.
- The per-party rules in `PartyRelationship.redaction_rules`.
- (Optionally) the recipient's declared red-flag patterns, applied as a courtesy.

Redaction is at the **transmit seam**: the durable local record is unredacted; the wire payload is redacted; the recipient's mirror is also redacted.

### 6. Authority on cross-mind Artifact mutation

When party B writes to an Artifact that party A authored (via the transport delivering an inbound Edit), authority is checked at the inbound seam:

- The Artifact's local `write_acl` is checked — does it permit the remote identity at all?
- The `PartyRelationship.inbound_write_policy` for B is checked — `accept` (apply directly), `review` (queue as a proposed edit for human review), or `reject` (refuse).
- The transport's signature verification confirms the edit actually came from B.

There is no separate cross-mind authority primitive for Mailboxes (Mailboxes don't cross minds) or for AttentionRequests (those don't cross minds either — see below).

### How cross-mind notification works (without cross-mind Emissions)

When mind A wants mind B's attention on something — a disagreement, a proposal, a request for input — the mechanism is:

1. Mind A writes an Artifact whose schema models the notification (e.g. `ProposalArtifact`, `DisagreementArtifact`, `AttentionRequestArtifact`).
2. The Artifact is published to mind B with appropriate visibility.
3. The transport syncs the new Artifact version into mind B's sensorium.
4. Mind B's local `artifact.<name>.changed` emission fires (in mind B's mind, from B's perspective).
5. B's relevant Stream / Supervisor reacts as if a local artifact change had landed.

Mind A does not "send" anything to mind B's Mind directly. The Artifact-state exchange handles it.

This unifies cross-mind notification with the rest of the sensorium-based interaction model. The cost: mind A's notification arrives at mind B's speed (transport latency + B's subscription cadence), not synchronously. For the cases plan-collaboration cares about — disagreements that can't be immediately resolved, scaling across project boundaries — that latency is appropriate.

### Disagreement / negotiation: composing with [[plan-984dfeb]]

The disagreement case (two minds with separate goals that don't immediately agree) is naturally an Artifact lifecycle:

- Mind A publishes a proposal (`ProposalArtifact`) at `visibility=Party(B)`.
- Mind B reads it, may publish a counter-proposal or amendment (linking back to A's proposal via `[[...]]`).
- Either side may invoke a mediation pattern (a third-party Artifact, an agreed-upon resolution protocol).
- Eventually one of: convergence (a shared Artifact version both endorse), recorded split (each side keeps its version, the disagreement is logged), or abandonment.

This is what [[plan-984dfeb]] (living artifacts) operationalizes. Plan-collaboration provides the substrate (Artifact publishing + transport + identity); plan-984dfeb adds the negotiation primitives.

## Implementation PR

One PR lands the cross-mind substrate after plan-sensorium's Artifact substrate PR is in. The substrate is small (six files) but has subtle transport-layer questions; one focused PR keeps them coherent.

### PR: Cross-mind substrate

**Purpose.** Land the narrow typed cross-mind substrate that enables Artifact-mediated interaction between two pm minds without relying on the broader public sensorium.

**Scope.**
- In: `pm_core/collaboration/identity.py` (ProjectIdentity + PartyRelationship + IdentityService — attribution via transport metadata + optional version signing, NO Emission signing); `pm_core/collaboration/published_artifact.py` (PublishedArtifact extension to Artifact — `published_to: set[str]`, `publish_visibility: dict[str, VisibilityTier]`, `publish_to_project(project_id, tier)`, `unpublish(project_id)`); `pm_core/collaboration/transport/protocol.py` (Transport Protocol — `publish`, `fetch`, `subscribe`, `authenticated_as`); concrete transports `transport/git.py` (commit + push), `transport/https.py` (push/pull against a relay or peer endpoint), `transport/tmux_socket.py` (same-host shared tmux socket).
- Out: Tracks A-F of this plan (existing radar / shadow / demo / trust scope — those use the substrate this PR lands but are independent plan work).

**Public API.** `ProjectIdentity` (Payload): `project_id, display_name, signing_pubkey, party_relationships: dict[str, PartyRelationship]`. `PartyRelationship`: `visibility, redaction_rules, transport: TransportConfig, inbound_write_policy: 'accept'|'review'|'reject'`. `IdentityService.attribute(artifact, version) -> ProjectIdentity` (who authored from transport metadata), `.sign_version(artifact, edit)` (optional explicit Artifact-version signing on top of transport-level signing), `.verify_version(artifact, version)`. `Artifact.publish_to_project(project_id: str, tier: VisibilityTier)` extends the Artifact base. `Transport` Protocol with `publish(artifact, edit, to: ProjectIdentity) -> PublishReceipt`, `fetch(from_project, artifact_name, since_version) -> list[Edit]`, `subscribe(from_project, artifact_glob, handler) -> SubId`, `authenticated_as() -> ProjectIdentity`.

**Invariants.**
- Cross-mind interaction transports **Artifacts**, not Emissions. There is no FederatedMailbox; there is no SignedEmission. Emissions stay inside a mind.
- Transport-level authentication (git commit signatures, HTTPS TLS) is the default. Explicit Artifact-version signing is optional, used when stronger authorship guarantees matter than the transport provides.
- `Artifact.apply()` on a published Artifact triggers transport sync to all `published_to` projects after the local commit lands.
- Inbound edits from a remote party are subject to BOTH the local Artifact's `write_acl` AND the relationship's `inbound_write_policy`. An edit accepted by the policy still goes through schema validation.
- `Transport` does NOT publish an Artifact whose visibility tier is below the recipient party's authorized tier. Visibility violations raise on outbound, not just at receive.

**Dependencies.** `pm_core/sensorium/artifact/` (Artifact base — extended by PublishedArtifact). `pm_core/payloads/` (Payload Protocol for ProjectIdentity). `pm_core/mind/` (VisibilityTier with Party variant; RedactionPolicy for redaction overlays at the transmit seam — RedactionPolicy is defined in plan-sensorium PR3).

**Test plan.** PublishedArtifact end-to-end with `git.py` transport: ProjectA publishes → ProjectB pulls + reads via standard Artifact API. Visibility violation on outbound: an Artifact with `visibility=private` cannot be published to a party. Inbound write policy: a remote edit lands as `accept` / queues for review / refuses based on `PartyRelationship.inbound_write_policy`. Cross-relationship redaction overlay: the same Artifact published to two parties at different tiers gets different redacted views. Transport substitutability: ProjectA + git ↔ ProjectB + https interop (both implement the same Protocol).

**Migration plan.** No existing pm code maps to this PR. The substrate is net-new; existing plan-collaboration Tracks (A-F) will consume it as it lands, then themselves migrate from "envisioned" to "implementable." `pm/identity/` directory convention (for commit-signed public keys) is established as part of this PR; the manual `pm collab trust <project>` command lands here as a PmCommand subclass.

**Open questions.**
- Transport for MVP: `git.py` first (no infrastructure, OSS-native, naturally async); `https.py` and `tmux_socket.py` follow as additive leaf changes.
- Identity / key distribution: `ProjectIdentity.signing_pubkey` exchanges piggyback on git (commit-signed public keys in `pm/identity/`) with a manual `pm collab trust <project>` to authorize a relationship.
- Per-project vs. per-relationship `PartyRelationship`: per-relationship — one identity can advertise different transports / tiers to different parties.
- Inbound-edit batching: when a remote party publishes 50 edits in rapid succession, fire 50 `artifact.<name>.changed` emissions by default; transport may coalesce when delivery batches; callers opt into coalescing via `CallbackRegistry.on(...)` parameters.
- Disagreement protocol details (proposal, counter-proposal, mediation): deferred to plan-984dfeb (living artifacts); this PR provides the substrate, not the negotiation semantics.

## Migration placement

This PR lands after **plan-sensorium PR1 (Artifact substrate)** and ideally after **plan-sensorium PR3 (RedactionPolicy)** so that PublishedArtifact extends a complete Artifact base and per-relationship redaction overlays compose cleanly with the local RedactionPolicy.

Pre-substrate: the existing radar / shadow / demo Tracks (A-F) use within-one-mind primitives. Cross-mind transport becomes load-bearing at Track C (cross-pm protocol) and beyond; everything before that runs against the public sensorium (git + GitHub) without this substrate.

---

## Status counts

- pending: 0 (none filed yet; `pm plan load plan-collaboration` after approval)
- in_progress: 0
- merged: 0

## Notes / philosophy

- **The meritocracy thesis is contingent, not deterministic.** The plan delivers the substrate; whether the equilibrium actually shifts toward open depends on adoption, on the quality of the substrate, and on the specific competitive dynamics in each industry. The plan does not claim this future will arrive; it builds what would be needed if it does, and the substrate is useful at much smaller scale (one user, a few shadow projects) before any network effect appears.
- **The two force-multipliers — development power and attentiveness — both come from the agent infrastructure, not from the openness alone.** Openness without intelligent collaboration is a hard problem (it's been tried for decades, with mixed maintainer-overwhelm and brilliant successes); openness *with* intelligent collaboration is a new variable. This plan is what makes that new variable real.
- **Quiet defaults are load-bearing.** A collaboration system whose defaults are "share everything" would be a privacy disaster and a contribution-spam vector. Defaults are `private` and gated; users opt into openness explicitly per artifact and per relationship. Reversibility matters too — anything published can be unpublished (within the limits of what's been mirrored).
- **The on-ramp's design principle is reciprocity, not extraction.** The shadow project produces value for the external party first; the user gets value if and when the external party engages back. This explicitly rules out parasitic patterns where pm extracts value from external projects without offering anything back. It also rules out surveillance patterns where pm watches external projects without giving them anything to claim.
- **Network effects favor early adopters of the substrate, but the substrate doesn't require network effects to be useful.** Even one user with a handful of shadow projects gets meaningful value (better attentiveness, candidate fixes for projects they care about). The MVP delivers that. The meritocracy outcome is the long-horizon thesis; the immediate value is the user-scale one.
- **The macro-scale demonstration of the cooperation thesis lives in its own sketch plan: `[[plan-simulation]]`.** If this plan's substrate matures and pm reaches the practically-free-software-dev threshold, that plan delivers the simulated-scenario testbed (diplomacy-style up to grounded global-resource models) in which the claim *"AI agents engaged as cooperative peers outperform purely self-interested optimization on common-good metrics over long horizons"* can be tested at civilizational scale. It is the macro version of this plan's micro vision; it is preconditioned on pm reaching maturity and is held as a sketch rather than committed scope.
- **Antitrust / anticompetitive dynamics worth naming.** If this substrate works, it advantages players who adopt it early and run it at scale — exactly the dynamic that produced platform monopolies in the previous wave of software. The substrate's design choices (quiet defaults, reciprocity, open output formats, no platform lock-in) are explicit countermeasures, but the question is not solved by them alone. Worth flagging here so future PRs in this plan consider it.
