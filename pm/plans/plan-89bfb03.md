# Living projects: self-sustaining forks that take input from the public

## Goal

A living project is a fork of an open-source project that pm keeps alive and that the public can watch and steer. Agents fix bugs and build features continuously. People follow the work as it happens and influence the plan through GitHub, social media and paid input into the visible sessions. Income from the people who value the project covers its running cost. The fork lives in its own protected environment, so attacks on the project cannot reach the owner's machine or other projects.

The first candidate is a tmux fork, once plan-delivery's D9 tmux campaign shows pm can fix tmux bugs on its own. Start hands-on, with the owner approving each public surface, and move toward full autonomy as evidence earns it. Open models make it affordable to run many projects indefinitely; frontier models remain an option when income pays for them.

## Decisions (owner, 2026-10-29)

- **What people pay for:** the animated, living version of the project: watching it work, and filtered input into its visible sessions. Paying for features people value is welcome. Large income from popular features is the market at work, and any surplus funds other work.
- **Self-sustaining on a small floor:** each project keeps running on a small monthly minimum that the owner pays personally. There is no expectation of large funding. Spending above the floor rises only with income actually received.
- **Licenses:** adopt only projects whose license permits a renamed, publicly developed and monetized fork. Permissive licenses such as tmux's ISC are straightforward. Copyleft is workable as long as the fork stays open source. The fork's name is separate from the license: every fork has its own name and says clearly that it is AI-maintained.
- **Original author:** if a project's income becomes significant, the owner shares part of it with the original author.
- **Paid input:** paid input may reach live, visible sessions through layered filtering and surrounding protections. At first the owner reviews every paid input by hand.
- **Isolation:** each project runs in its own isolated, continuously monitored VM with regular backups. The host never accepts public input.
- **Target forks, not upstream.** Testing must never crash the tmux that pm itself runs in.
- **Avatars:** more direct engagement through avatars waits until it is affordable.

## Security model

Public input is the main threat. Once comments, chat and paid messages influence planning, anyone can write text that an agent with access to the code will read. Several layers apply at once:

1. **Public input is data, never instructions.** Every source (issues, comments, pull requests, social media, stream chat, paid messages) lands in a store of untrusted input. A triage step without privileges turns it into attributed proposals. The owner or the judge panel (`pr-204f09e`) decides what enters the plan.
2. **Change filtering.** Every change to the fork passes pm's review, QA and sign-off. A change that came from public input carries its source, and review checks it for adversarial intent: backdoors, data exfiltration, weakened security, unexpected network access and license contamination.
3. **Paid input has limited authority.** It reaches a session as an attributed request that the agent weighs, the way it weighs an issue comment. It cannot touch credentials, the budget or owner gates, and it cannot trigger a push.
4. **Agents never hold money or stream credentials.** Payouts go to accounts the owner controls. The stream is captured outside the project VM. Push access follows plan-a35369f's rule: only the sign-off session pushes, using a credential scoped to the fork.
5. **The VM boundary also holds in reverse.** Host-side monitoring pulls data out of the VM and treats everything it reads as untrusted. Any agent that reads VM output holds no privileges, so an injection cannot cross the boundary through the monitor.
6. **Backups are out of the VM's reach.** Snapshots are written where the VM cannot delete or modify them, and restoring them is tested. Each fork has the same no-force-push, no-deletion ruleset as this repository.
7. **The stream is not a leak channel.** Viewers see a curated activity view with a delay and secret redaction, never the raw terminal. Text from the public is moderated before it is displayed.
8. **Everything is audited.** Each public or paid input is recorded with its source, the filter decision and what the project did with it, so abuse can be traced, refunded and blocked.

## Stages

The owner approves each step to the next stage, using evidence criteria set in the charter: the red-team suite passing for the new surfaces, a completed restore drill, no unresolved security incidents, and spending within budget.

0. **Private.** The tmux fork runs in its VM. It is not public, and the owner approves its work.
1. **Public to watch.** The repository is public, with a delayed, curated stream.
2. **Public input.** GitHub and social media input is triaged into proposals.
3. **Payments.** Income from viewers and paid input into the visible sessions, with every paid input reviewed by the owner.
4. **Less owner gating.** Paid-input filtering is automated one category at a time once it matches the owner's past decisions; agents gain autonomy elsewhere as evidence supports it. A second project can be adopted.
5. **Avatars,** when affordable.

## Relationship to other plans

- **plan-delivery:** D9's tmux campaign qualifies pm on tmux in isolated test servers. This plan carries the result into a public, self-sustaining fork. D3's agent-controlled execution and the bug watcher's security-first selection drive the work. The scheduled brief (`pr-2588ead`) is where the owner sees escalations, income and spending.
- **plan-a35369f:** sign-off-only push (`pr-1e932fc`), the least-privilege agent identity (`pr-47765ea`) and the red-team approach (`pr-2883eb0`) all apply inside each project VM.
- **Judge panel:** `pr-204f09e` and the owner route decide public proposals and paid requests that need a decision. By default, spending, credentials and security go to the owner.

Existing-ID edges, added at registration: the fork bootstrap (`pr-713fb08`) depends on `pr-1e932fc`, `pr-47765ea` and `pr-f4dc8a2` (initial regression audit). Public-input triage (`pr-0d491bf`) depends on `pr-204f09e`. Every PR in this plan has `review_spec: true`.

## PRs

### PR: Living-project charter with stage gates and platform review
- **description**: Write the charter the rest of this plan builds on, as a spec for owner approval (review_spec). Record the owner's decisions above. Define the evidence criteria for each stage gate. Write the project admission check: license terms for a renamed, monetized public fork; a fork name distinct from upstream's; and the AI-maintained disclosure. Set the author-share policy and decide when a fix is offered upstream (only after owner review). Choose where VMs run (on this host or rented) and estimate the monthly floor for each option, using observed model and compute costs rather than guesses. Choose the payment provider and how payouts reach the owner. Review the current terms of GitHub (machine accounts, automation), the chosen streaming service (automated and AI-generated streams) and the payment provider; record what each permits and requires, citing sources. Legal and tax obligations remain the owner's; the plan only keeps the records they need.
- **tests**: None (spec). Reviewed and approved by the owner.
- **files**: pm/docs/living-projects.md
- **depends_on**:

### PR: Isolated project VM with external monitoring and backups
- **description**: Each living project runs in its own VM. The VM has no host mounts holding credentials and no access to the host tmux socket or to pm's own sessions. Outbound network access is limited to an allow-list: the fork's git host, the model endpoints, package mirrors and the stream ingest. Host-side monitoring pulls resource use, processes, git refs and outbound connections, alerts the owner on anomalies, and offers pause and kill switches. It treats everything it reads as untrusted, and no agent that reads VM output holds privileges. Snapshot backups go to storage the VM cannot write, with a scripted, tested restore. Resource limits keep a project from starving pm or other projects on shared hardware.
- **tests**: Sandbox checks from inside a VM: host services are unreachable, the host tmux socket is unavailable, network access outside the allow-list fails, and backups cannot be deleted or modified. A restore drill rebuilds a project from a snapshot. A planted injection in VM logs does not change what the monitor does.
- **files**: pm_core/living/vm.py, pm_core/living/monitor.py, docs
- **depends_on**: Living-project charter with stage gates and platform review

### PR: Red-team regression suite for living projects
- **description**: A suite that attacks a sandboxed living project: a local fake GitHub, fake social-media and stream-chat sources, a fake payment provider and a local stream sink, with no real network endpoints. Initial cases: injected instructions in issues, comments, pull requests, chat and paid messages; attempts to get secrets onto the stream; attempts to change the budget or trigger a push through public or paid input; injections aimed at the monitor through VM output; and backup tampering. Each later PR in this plan adds cases for its own surface. Every case checks the actual outcome (refs, budget state, stream output, backup contents), not just exit codes. Also add a prompt for an agent-driven red-team session limited to the sandbox, which turns each new finding into a test case.
- **tests**: The suite itself.
- **files**: tests/test_living_redteam.py, tests/fixtures/
- **depends_on**: Isolated project VM with external monitoring and backups

### PR: Bootstrap the first living project: a tmux fork
- **description**: Stage 0. Run the charter's admission check on tmux. Create the renamed fork under an account the owner controls, with an AI-maintained notice in the README. Apply a no-force-push, no-deletion ruleset. Give the sign-off session a push credential scoped to the fork only. Set up a pm project inside the project VM and run the initial regression audit (`pr-f4dc8a2`). The tests use isolated tmux servers that never touch the tmux pm runs in. Seed the plan from D9's campaign results and `pr-e29dda7`. The fork stays private, and the owner approves its work until the stage 1 gate.
- **tests**: The fork's ruleset rejects a force push and a branch deletion. Only the sign-off session can push, and only to the fork. Crashing a tmux build under test leaves pm's own tmux server running. The owner can pause and resume the project.
- **files**: pm_core/living/bootstrap.py, docs
- **depends_on**: Red-team regression suite for living projects

### PR: Budget governor with a monthly floor and income-backed spending
- **description**: Each project has a monthly floor set by the owner. Track spending (model API usage, VM hosting and an estimate for local compute) and income against it in a ledger. Spending above the floor is allowed only against income already received. When the budget runs out, the project slows to floor-level activity, for example open models only, instead of stopping. Agents and public or paid input cannot change the budget; only the owner can. Report spending, income and remaining budget in the scheduled brief (`pr-2588ead`) and keep records for the owner's accounting.
- **tests**: Spending stops at the floor with no income and resumes after recorded income. An attempt to change the budget from a session, public input or paid input is refused (red-team case). The ledger reconciles with provider usage records in a sandbox.
- **files**: pm_core/living/budget.py, docs
- **depends_on**: Living-project charter with stage gates and platform review

### PR: Delayed and curated activity stream
- **description**: Stage 1. Stream a curated view of the project's activity: the current plan and PRs, recent commits and test results, and redacted excerpts of session transcripts. Never stream the raw terminal. Capture the view outside the project VM in a component that holds the stream key and never reads public input. Apply secret redaction (reusing the credential-redaction work from `pr-42425ab`) and a configurable delay, so a leak can be cut before it airs. Moderate public text before it appears on screen. Stream chat is public input: it goes to the untrusted-input store, not to the streaming component. The owner has a kill switch.
- **tests**: Secrets planted in a session never reach the stream sink. The delay lets the kill switch remove content before it airs. Offensive or injected text from a fake public source is not displayed unmoderated. The streaming component has no route to read public input.
- **files**: pm_core/living/stream.py, docs
- **depends_on**: Bootstrap the first living project: a tmux fork

### PR: Public input triage into attributed proposals
- **description**: Stage 2. Adapters for GitHub issues, comments and pull requests, and for the social-media accounts chosen in the charter, write to a store of untrusted input. A triage agent with no privileges and no tools beyond proposing groups duplicates, screens for injection and abuse, and turns input into attributed proposals: bugs, feature requests and plan changes. Proposals go to the judge panel (`pr-204f09e`) or to the owner under the owner's guidance. Rate limits and per-source reputation keep floods and spam down. Paid input gets higher priority but goes through the same screening.
- **tests**: Red-team injection cases in each source produce at most a flagged proposal, never an action. Duplicates merge. A flood from one source is rate-limited. An accepted proposal becomes a PR that records its source.
- **files**: pm_core/living/inputs.py, pm_core/living/triage.py, pm_core/prompt_gen.py, docs
- **depends_on**: Bootstrap the first living project: a tmux fork

### PR: Review checks public-derived changes for adversarial intent
- **description**: Every PR derived from public or paid input carries its source through implementation, review, QA and sign-off. For such PRs, the review and QA prompts check for backdoors, data exfiltration, weakened security checks, unexpected network or credential access, and license contamination from pasted code, and they scrutinize the change more closely than an owner-originated one. Pull requests from the public are treated as untrusted proposals: an agent reimplements or reviews them, and they are never merged as submitted without that review.
- **tests**: Seeded public requests that smuggle a backdoor, a telemetry call or a weakened check are flagged in review. The source survives every stage. An ordinary public bug fix passes normally.
- **files**: pm_core/prompt_gen.py, pm_core/living/triage.py, tests
- **depends_on**: Public input triage into attributed proposals

### PR: Payments and owner-reviewed paid input into visible sessions
- **description**: Stage 3. Integrate the charter's payment provider. Payouts go to the owner's account, and no agent or project VM holds payment credentials. A paid message enters a queue, and at first the owner approves or rejects every one. An approved message reaches the live session as an attributed request the agent weighs, with the authority limits in the security model. Record each paid input with payer, payment, filter and owner decisions, and what the session did with it. Support refunds and blocking abusive payers. Income goes to the budget ledger. Each owner decision is saved as a labeled example for the automated filter.
- **tests**: With a fake payment provider: an approved message reaches the session with attribution; a rejected one never does; a paid message cannot change the budget, credentials or gates, or trigger a push (red-team cases). The audit record links payment, decisions and outcome. A refund reverses the ledger entry.
- **files**: pm_core/living/payments.py, pm_core/living/inputs.py, docs
- **depends_on**: Public input triage into attributed proposals, Delayed and curated activity stream, Budget governor with a monthly floor and income-backed spending

### PR: Automate paid-input filtering one category at a time
- **description**: Stage 4. Once the owner's review history covers a category of paid input, let an automated filter decide that category only when it matches the owner's past decisions and passes the red-team injection cases. Uncertain cases still go to the owner. The owner can return any category to manual review at any time. Report the filter's agreement with the owner and any decisions the owner reverses.
- **tests**: A category stays manual until agreement is shown on held-out owner decisions. Red-team cases are rejected. Uncertain inputs go to the owner. Returning a category to manual takes effect immediately.
- **files**: pm_core/living/filter.py, pm_core/prompt_gen.py, docs
- **depends_on**: Payments and owner-reviewed paid input into visible sessions

## Later

- A second living project, after stage 4 on tmux.
- Avatars, when the cost allows.
