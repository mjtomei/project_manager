# Open lab infrastructure planning

Internal planning document for the mesh and chain layers of the open
source research lab. See `plans/open-lab.md` for the public-facing
design. This document covers the OmertaMesh and OmertaProtocol
integration that extends the lab beyond GitHub.

## The mesh layer (OmertaMesh)

The mesh layer is for organizations that want to minimize human
contact overhead, enable cross-org data movement, manage trust between
organizations, or allow AI agents to participate as first-class
members of the network. The org repo and pm repo work fine on GitHub
without any mesh infrastructure. The mesh becomes relevant when the
organization outgrows what a single platform provides.

For organizations that use it, the lab runs on an OmertaMesh where
researchers are peers. No central servers. No single point of control
or failure.

The mesh provides:
- **Communication**: researchers talk to each other directly, not
  through a platform someone else controls
- **Discovery**: find other researchers, their projects, their
  published work — all through the mesh's gossip network
- **Collaboration**: share workspaces, review code, pair on problems
  without routing through GitHub or any other third party
- **Resilience**: the lab doesn't depend on GitHub staying up, or
  any cloud provider, or any single country's legal framework

## The gossip layer

The following is a case study of how a gossip network could be built
on top of an academic organization. The same patterns apply to any
organization that manages resources and produces work products — the
specifics would change but the structure is the same.

Built on OmertaMesh's gossip network, the lab tracks:

- **Grants and funding**: who received what, from whom, for what purpose.
  Announced to the network when received. Allocation decisions are
  proposals that go through governance.

- **Gifts**: unrestricted contributions to the lab or to individual
  researchers. Tracked in the gossip network so the community can see
  the flow of resources without anyone having to report to a central
  authority.

- **Stipends**: regular support for researchers. Terms are public.
  Continuation is tied to participation (defined by governance docs,
  not by a manager's discretion).

- **Scholarships**: support for people learning to contribute. Tracked
  the same way as stipends but with different expectations (learning
  vs. producing).

- **Work products**: papers, code, datasets, tools, analyses. Published
  to the gossip network with attribution. The network maintains a
  living record of what the lab has produced and who contributed.

All of these are gossip-native: they propagate through the network
without requiring any central database. Any node can verify the
history. The data is eventually consistent — if you're offline for
a week, you catch up when you reconnect.

## The chain layer (OmertaProtocol)

The problems with academia that this addresses are structural:
implicit systems of credit, funding, and access that are understood
by insiders but invisible to outsiders and unaccountable to anyone.
Academics prefer minimal top-down structure — they resist heavy
management. The chain layer respects this by providing visibility
without requiring hierarchy. It makes the existing implicit systems
explicit and directly engineerable. Instead of "everyone knows how
tenure decisions really work," the process is on chain and anyone
can read it, verify it, or propose changes to it.

Later in the tech tree, the gossip-tracked items move to OmertaProtocol.
This provides:

- **Immutability**: once a grant, gift, or work product is recorded on
  chain, it can't be retroactively altered
- **Verifiability**: anyone can independently verify the lab's financial
  and research history without trusting any single node
- **Interoperability**: other labs, funders, and institutions can read
  the lab's records programmatically — explicit and directly engineerable
- **Persistence**: the record outlives any individual node, any
  individual researcher, and potentially the lab itself

The gossip layer is the fast, informal layer — things show up quickly,
propagate naturally, and can be corrected. The chain layer is the
permanent record — things are committed deliberately and stay forever.

The transition from gossip to chain is not automatic. It's a governance
decision: the lab decides what gets committed to the permanent record
and when. This prevents premature permanence (recording something on
chain before the community has had time to review it).

The chain doesn't replace existing accounting, reporting, or compliance
structures. A grant that's tracked on chain is also tracked in whatever
system the fiscal sponsor uses. The chain is a parallel record that
provides independent verifiability — useful for the lab's own
transparency and for anyone who wants to audit the lab without relying
on a single institution's books.

The chain layer also provides mechanisms for attesting to work
associated with money — who did what, funded by whom, producing what
output. These attestations are useful regardless of how the money
moved. People might eventually choose to move money around only with
the guarantees provided by the open lab's infrastructure, but that's
their choice, not a requirement for participation.

## Full tech tree

### Layer 0: Foundations (all parallel)

- **Organization repo structure** — Create the org repo with `docs/`
  (golden copy), `members/` (per-member directories), `checks/`
  (integrity checks), `archive/`. Seed governance, onboarding, and
  CONTRIBUTING guide. Include pointers to all other repos so it
  serves as central dispatch.

- **Member directory workflow and templates** — Templates for member
  directories. PR workflow for promoting work from `members/` to
  `docs/`. Branch protection for `docs/` requiring review. *(depends
  on: org repo structure)*

- **Integrity checks framework** — Framework for `checks/` directory.
  Initial checks: consistency, staleness, completeness, attribution.
  CI integration. Audit history for both automated and human-assisted
  reviews. *(depends on: org repo structure)*

- **OmertaMesh network setup** — Bootstrap the mesh for the lab.
  Founding nodes, peer discovery, researcher onboarding.

- **PM repo and recursive tech tree** — Separate pm repo. Recursive
  tech tree connecting org-level management to research projects.
  Integrates with `plans/recursive-tech-trees.md`.
  *(depends on: org repo structure)*

### Layer 1: Operations and gossip infrastructure

- **Resource tracking in the org repo** — Structure for `docs/resources/`.
  Templates for grants, allocation decisions, budgets. Integrity
  checks that validate resource numbers. Works for both public and
  private funding. *(depends on: member workflow, integrity checks)*

- **Gossip schema for resource tracking** — Message types for grants,
  gifts, stipends, scholarships. Schema versioning, propagation rules.
  Mirrors the org repo but propagates without GitHub.
  *(depends on: org repo, mesh setup)*

- **Gossip schema for work products** — Message types for research
  outputs. Attribution model. Links to funding sources.
  *(depends on: org repo, mesh setup)*

- **Researcher identity on the mesh** — Key-based identity. Optional
  link to GitHub identity. Reputation is visible history, not a score.
  *(depends on: mesh setup)*

- **AI integrity checks** — Claude-powered checks beyond structural
  validation: flag contradictions in governance docs, unsupported
  claims in proposals, budget anomalies, decisions that contradict
  stated governance. The BS detectors. *(depends on: integrity checks
  framework, resource tracking)*

### Layer 2: Lab operations

- **Funding receipt and allocation workflow** — End-to-end: receive
  funding, record in org repo, propose allocation via governance PR,
  track distribution. Integrity checks verify the full chain.
  *(depends on: resource tracking)*

- **Stipend and scholarship management** — Terms as governance docs.
  Continuation tied to participation defined by governance.
  *(depends on: resource tracking)*

- **Work product publishing pipeline** — Publish to member directory,
  PR to `docs/` with attribution and funding source. Integrity checks
  verify links. *(depends on: resource tracking)*

- **Automated recognition system** — Scripts and Claude-powered
  analyses detecting achievements: milestone completion, first
  contributions, sustained output, unblocking cascades, completed
  deliverables, cross-project collaboration. Criteria are code in
  the repo. Outputs a feed for dashboards. *(depends on: AI integrity
  checks, all layer 2 workflows)*

- **Lab dashboard** — Mobile web dashboard showing recursive tech
  tree, resource flows, researcher activity, org health, recognized
  achievements. Does the noticing so the organization sees what its
  members accomplish without self-promotion. *(depends on: PM repo,
  all layer 2 workflows, recognition system)*

### Layer 3: Permanent record (OmertaProtocol)

- **OmertaProtocol integration design** — Design the gossip-to-chain
  transition. What gets committed, when, by whose authority (governance
  decision). Smart contract interfaces. Chain parallels org repo and
  gossip — doesn't replace existing accounting. *(depends on: all
  layer 2 workflows)*

- **Funding and resource tracking on chain** — Immutable funding
  history on OmertaProtocol. Attestations of work associated with
  money. Useful alongside traditional accounting. *(depends on:
  integration design)*

- **Work product provenance on chain** — Permanent attribution.
  Funding links. Citation graph nobody controls and everybody can
  verify. *(depends on: integration design)*

- **Lab history and institutional memory** — Complete record on chain.
  What was funded, produced, who participated, how decisions were
  made. Survives any node, any researcher, any generation of the lab.
  The org repo on GitHub is a convenient interface; the chain is the
  permanent copy. *(depends on: funding on chain, provenance on chain)*

## Open questions

- **Legal entity**: does the lab need a legal entity for receiving
  grants? Probably yes, at least initially. How does a legal entity
  map to an open-source governance process?

- **Conflict resolution**: governance PRs can be contentious. What's
  the escalation path? Probably: discuss in the org repo, propose
  via PR, decide by whatever process the governance docs specify
  (which is itself changeable via PR).

- **Bootstrap problem**: the first version of governance has to come
  from somewhere. It can't be voted on by a community that doesn't
  exist yet. Accept this and make the initial governance explicitly
  provisional — "this is the starting point, here's how to change it."

- **Forking**: if someone forks the lab, do they fork the resource
  history? The reputation history? Probably: they fork the governance
  and structure but not the resources (you can't fork money) or
  reputation (you can't fork trust). They start fresh with a new
  network that happens to use the same rules.
