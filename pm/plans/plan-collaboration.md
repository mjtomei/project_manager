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

- **`[[plan-radar]]`** — external-overlap detection is a direct extension of the radar's source-and-triage machinery; the navigation primitive and editable-artifacts primitive are reused wholesale. This plan's MVP cannot ship until radar's MVP does.
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

Plans, PRs, threads, notes, captures all gain a `visibility` field: `private` (default) / `share-on-request` / `public`. Editable by the user or via the editable-artifacts chat. Schema-validated, audit-logged on change.

### PR: Public-facing surface generator

`pm publish` (or similar): static export of artifacts marked `public` to a configured path / git repo / S3 bucket / etc. Output includes plan titles + summaries, recent thread items above a relevance threshold, sign-off reports for merged PRs — whatever the user has opted into. Read-only for v1.

### PR: Inbound interaction model

Initially read-only: anyone with the URL can read public artifacts. Commenting and proposal flow come later (Tracks C and F). The point of v1 is reachability without exposure to spam or attack surface.

---

## Track C — Cross-pm-project collaboration protocol (both parties use pm)

When both parties run pm, a richer collaboration protocol becomes possible: artifact sync across projects, proposal flow via the editable-artifacts primitive, conflict resolution when parallel work diverges.

### PR: Project-to-project artifact-sync protocol

Define the wire format and trust model. Shared threads land in both projects' radars; comments propagate (with provenance). Per-artifact opt-in: the user explicitly chooses which threads / plans / PRs sync to which peer projects.

### PR: Cross-project proposal flow

When the triage agent on project A surfaces a `collaboration-candidate` feature targeting project B, it can prepare a proposal that lands on project B's preferences-chat surface as a candidate edit. Project B's user reviews and accepts / rejects via the same editable-artifacts mechanism they use for their own preferences.

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
