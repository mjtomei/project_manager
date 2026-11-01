# Example rendered briefs (pr-2588ead)

Supplements [`../impl.md`](../impl.md); the spec wins on any disagreement.

These briefs are representative. pm's renderer (impl §1.5, R7) writes the
title, as-of line, headline counts, status labels, links and footer. The
composer, following prompt P1, writes only the line text and grouping. Once
implemented, the golden-render tests (impl §13) regenerate every brief below
from fixtures, and QA (impl §14) captures real ones.

**Data provenance** (as in [`notes-and-state.md`](notes-and-state.md)):

- B0 is rendered from this workdir's **real** registry snapshot.
- In B1–B8, project-manager uses real PR ids, titles and numbers. Its 2026-11-01
  merges are the real merges on `master`; everything after 2026-11-01 is
  illustrative.
- cosmic_ac and omerta-core are **illustrative fixtures** standing in for the
  D5 and D8 adoption projects.
- Times are `America/Chicago`.

Label legend: `[waiting <age>]`, `[failed <age>]`, `[merged · auto]`,
`[merged · owner-approved]`, `[merged · path not recorded]`, `[running]`,
`[planned]`, `[stale]`, `[unavailable <age>]`, `[resolved]`, `[now]`
(position) and `[guidance]`. `→` starts pm's links. When one line covers
several items, each link carries that item's age.

---

## B0 — Real data: plain preview from this workdir's registry (Sun 1 Nov 2026, 14:45 CST)

`pm brief preview --plain` for project-manager alone, run from this PR's
workdir clone. This clone's `project.yaml` is a snapshot, not the hub's synced
registry, and pm says so.

What the brief shows from the real data:

- `last_pr_sync` is 2026-03-02.
- `pr-049649a` appears twice in the registry.
- None of the four merges on `master` today is recorded in this snapshot, so
  none is claimed.

There is no TUI in this container, so live status is unavailable.

```text
Owner brief "preview" · 1 project · PREVIEW (not published)
As of Sun 1 Nov 2026 14:45 CST · covers Sat 31 Oct 15:45 CDT → Sun 1 Nov 14:45 CST (24h; baseline) · run preview-20261101T204500Z-77aa
1 needs you · 0 merged · 0 blockers · all projects refreshed (project-manager partial: no live status)

project-manager
  [stale]  Registry last synced with GitHub on 2 Mar; merges made on GitHub since then may be missing here.
           → pm -C /workspace/pm pr sync
  [stale]  Registry has 2 entries for pr-049649a (#267); showing the one updated 1 Nov 03:21.
           → pm -C /workspace/pm pr show pr-049649a
  [unavailable]  Live run state not checked (no TUI for pm-project_manager-c5a1006b); waits and failures may be missing.
  [waiting 37m]  #287 Scheduled concise multi-project progress and change briefs: spec waits for your approval.
           → #287 · spec
  [stale]  42 open PRs have had no recorded activity for 7+ days (35 in review, 5 in QA, 2 in progress; oldest #104).
           → pm pr list -t
  [now]  12 in progress · 36 in review · 7 in QA · 0 at sign-off · 392 pending.

Plain brief (composer not used): preview --plain · Feedback: pm brief feedback
```

The plain renderer follows P1's default shape: owner decisions first, then
issues, then position. Registry data problems are required items, so no
guidance can hide them.

---

## B1 — First brief (baseline), Mon 2 Nov 2026 08:30 CST

This is run `20261102T143000Z-4f1a`. It was composed under the setup guidance
([`notes-and-state.md`](notes-and-state.md) §1), from the input and draft in
§6–§7 there.

The Markdown file (`captures/briefs/owner/20261102T143000Z-4f1a.md`, also
`latest.md`):

```markdown
# Owner brief "owner" · 3 projects

As of **Mon 2 Nov 2026 08:30 CST** · covers Sun 1 Nov 08:30 → Mon 2 Nov 08:30 CST (24h; baseline) · run `20261102T143000Z-4f1a`

**2 need you · 6 merged (1 auto, 1 owner-approved, 4 path not recorded) · 1 blocker · omerta-core not refreshed**

## cosmic_ac
- `waiting 1d 23h` #46 Refactor plotting helpers is signed off and held for your merge. — [#46](https://github.com/fixture-owner/cosmic_ac/pull/46) · [report](http://127.0.0.1:8765/p/5e1c0a77/pr-c46b7a2/report.html)
- `failed · new` #47 HEALPix mask support: review could not start (claude exited before its first turn). — [#47](https://github.com/fixture-owner/cosmic_ac/pull/47) · launch log `~/.pm/transcripts/auto-77d1/review-pr-c47e5d4-i2.launch.log`
- `merged · auto` #41 Add CMB power-spectrum loader. — [#41](https://github.com/fixture-owner/cosmic_ac/pull/41) · [report](http://127.0.0.1:8765/p/5e1c0a77/pr-c41a2b0/report.html)
- `merged · owner-approved` #44 Fix unit conversion in redshift binning. — [#44](https://github.com/fixture-owner/cosmic_ac/pull/44) · [report](http://127.0.0.1:8765/p/5e1c0a77/pr-c44d9e1/report.html)
- `now` 2 in progress, 2 in review, 1 in QA, 1 at sign-off, 3 pending; CMB pipeline 6/11 merged.
- `waiting 1d 23h` Next: merge or hold #46. — [#46](https://github.com/fixture-owner/cosmic_ac/pull/46)

## project-manager
- `waiting 18h` Spec for #287 (scheduled owner briefs) is waiting for your approval before implementation. — [#287](https://github.com/mjtomei/project_manager/pull/287) · [spec](https://github.com/mjtomei/project_manager/blob/pm/pr-2588ead-scheduled-concise-multi-project-progress-and-chang/pm/specs/pr-2588ead/impl.md)
- `merged · path not recorded` bugs plan: #272 PR close keeps history and workdirs; #280 no host fallback in container mode; #267 auto-start fails closed. — [#272](https://github.com/mjtomei/project_manager/pull/272) · [#280](https://github.com/mjtomei/project_manager/pull/280) · [#267](https://github.com/mjtomei/project_manager/pull/267) · reports: [272](http://127.0.0.1:8765/pr-62ad13d/report.html) [280](http://127.0.0.1:8765/pr-574e851/report.html) [267](http://127.0.0.1:8765/pr-049649a/report.html)
- `merged · path not recorded` improvements plan: #282 role-neutral model routing names and docs. — [#282](https://github.com/mjtomei/project_manager/pull/282) · [report](http://127.0.0.1:8765/pr-e076433/report.html)
- `stale` 42 open PRs have had no activity for 7+ days (oldest #104, since 23 Mar). — `pm pr list -t`
- `now` 9 in progress, 36 in review, 7 in QA, none at sign-off, 391 pending; bugs 22/239 and improvements 14/57 merged.
- `waiting 18h` Next: review the #287 spec. — [#287](https://github.com/mjtomei/project_manager/pull/287)

## omerta-core
- `unavailable · new` Could not refresh: project.yaml not found; no earlier data.

---
Feedback: `pm brief feedback` · Guidance: `pm brief guidance show` · All items: [details](20261102T143000Z-4f1a.html#details)
```

Why each part reads as it does:

- **Merge labels.** project-manager's four merges say "path not recorded" even
  though the owner approved them individually. Nothing in pm recorded how they
  merged, so the brief does not claim it. Labels become "owner-approved" only
  once a provenance record exists (impl R5, A1 pending). cosmic_ac's fixture
  merges carry `merge_record`s, so they are labelled auto and owner-approved.
- **Project order.** cosmic_ac comes first because it has more items waiting on
  the owner (setup guidance: "Order projects by what needs me").
- **Merge lines.** project-manager's merges name their plan (that project's
  guidance). Three are batched in one line under the default ">3 batch" rule.
- **Bounds.** The brief has 13 lines against a hard cap of 40; about 25 were
  requested.

The HTML page (`20261102T143000Z-4f1a.html`) shows the same lines, with status
chips and a collapsed **Details** appendix listing all 14 items with ids,
`since_source` and every link.

---

## B1′ — The same facts after the owner's correction (preview, Mon 2 Nov, 09:16 CST)

The feedback agent ran `pm brief preview --prepare --rerender
20261102T143000Z-4f1a` after applying r-…5a6b and r-…7c8d
([`conversations.md`](conversations.md) §2). The input is the same; only the
guidance changed.

```text
Owner brief "owner" · 3 projects · PREVIEW (re-composing run 20261102T143000Z-4f1a with current guidance)
As of Mon 2 Nov 2026 08:30 CST · covers Sun 1 Nov 08:30 → Mon 2 Nov 08:30 CST (24h; baseline) · run preview-20261102T151600Z-2d9c
2 need you · 6 merged (1 auto, 1 owner-approved, 4 path not recorded) · 1 blocker · omerta-core not refreshed

Needs you
  [waiting 1d 23h]  cosmic_ac #46 Refactor plotting helpers: signed off, held for your merge.  → #46 · report
  [waiting 18h]  project-manager #287: spec waits for your approval before implementation.  → #287 · spec
  [failed · new]  cosmic_ac #47 HEALPix mask support: review could not start.  → #47 · launch log

cosmic_ac
  [merged · auto]  #41 Add CMB power-spectrum loader.  → #41 · report
  [merged · owner-approved]  #44 Fix unit conversion in redshift binning.  → #44 · report
  [now]  2 in progress, 2 in review, 1 in QA, 1 at sign-off, 3 pending; CMB pipeline 6/11 merged.

project-manager
  [merged · path not recorded]  4 merged: bugs #272 PR close keeps history, #280 no host fallback in containers, #267 fail-closed auto-start; improvements #282.
           → #272 · #280 · #267 · #282 · reports
  [stale]  42 open PRs idle 7+ days (oldest #104, since 23 Mar).  → pm pr list -t
  [now]  9 in progress, 36 in review, 7 in QA, none at sign-off, 391 pending.

omerta-core
  [unavailable · new]  Not refreshed: project.yaml not found.

Feedback: pm brief feedback · Guidance: pm brief guidance show
```

What the correction changed, compared with B1:

- A cross-project **Needs you** list now comes first, oldest first.
- project-manager's merges are one line.
- omerta-core's notice is shorter.
- The brief is 11 lines instead of 13.

What did not change:

- cosmic_ac still lists its merges one per line. Its own guidance asks for
  that and the owner kept the exception; the project block wins for its own
  lines (impl §6).
- Every required item is still present.
- The labels and links are identical, because they come from data.

---

## B2 — Ordinary day under the new guidance, Tue 3 Nov 2026 08:30 CST

This is run `20261103T143000Z-8b2c`. Between briefs:

- cosmic_ac #45 auto-merged;
- #48 "Notebook: lensing tutorial" moved to QA, which the guidance leaves out
  because it is neither blocked nor waiting;
- #49 was filed;
- omerta-core's `project.yaml` now exists but does not parse;
- the owner edited project-manager's guidance directly (07:10).

```text
Owner brief "owner" · 3 projects
As of Tue 3 Nov 2026 08:30 CST · covers Mon 2 Nov 08:30 → Tue 3 Nov 08:30 CST (24h; 1 scheduled brief) · run 20261103T143000Z-8b2c
2 need you · 1 merged (1 auto) · 1 blocker · omerta-core not refreshed

Needs you
  [waiting]  Still waiting on you: cosmic_ac #46 merge (signed off), project-manager #287 spec approval.
           → #46 (2d 23h) · report · #287 (1d 18h) · spec
  [failed 1d]  Still failing: cosmic_ac #47 review cannot start.  → #47 · launch log

cosmic_ac
  [merged · auto]  #45 Add Planck likelihood wrapper.  → #45 · report
  [planned]  New: #49 Cache downloaded maps.  → #49
  [now]  1 in progress, 1 in review, 2 in QA, 1 at sign-off, 4 pending; CMB pipeline 7/12 merged.

project-manager
  [now]  No material change.

omerta-core
  [unavailable 1d]  Not refreshed: project.yaml does not parse (line 112).

Guidance changes since the last brief
  [guidance]  Whole brief: Needs-you list first, about 15 lines, merges batched, short unrefreshed notices (your feedback, Mon).
  [guidance]  cosmic_ac: "Notebook:" PRs left out unless blocked or waiting on you (your feedback, Mon).
  [guidance]  project-manager: direct edit in notes.txt adds "Mention when a PR touching containers merges."

Undo a change: pm brief guidance rollback <rev> (revs: pm brief guidance history) · Feedback: pm brief feedback
```

- **Unchanged items.** Unchanged waits are compressed into one "Still waiting"
  line with per-item ages.
- **Changed unavailable item.** omerta-core's reason changed (not found →
  parse error), so it gets a full line; its age runs from first seen.
- **Guidance changes are required items.** That includes the owner's direct
  edit, so every change to how briefs are written is visible in a brief.

---

## B3 — Delivery failure and retry, Wed 4 Nov 2026

Timeline (from `pm brief status`, `state.json` in
[`notes-and-state.md`](notes-and-state.md) §5.2–5.4):

| Time (CST) | Event | Boundary | `merge:5e1c0a77:pr-c50d8e2` published? |
|---|---|---|---|
| 08:30:00 | tick → prepare run `…143000Z-c3d4` (contains #50 owner merge, #47 resolved) | Tue 08:30 | no |
| 08:31:52 | draft valid → local delivery fails: `No space left on device` → no receipt, no commit; retry at 08:36:52 | Tue 08:30 | no |
| 08:36:52 | tick → re-prepare run `…143652Z-e5f6` (same interval start, new as-of) → delivery fails again; retry at 08:51:52 | Tue 08:30 | no |
| 08:50 | owner frees disk space | | |
| 08:51:52 | tick → run `…145152Z-0a1b` → delivered → receipt → commit | **Wed 08:51:52** | **yes (once)** |

The published brief:

```text
Owner brief "owner" · 3 projects
As of Wed 4 Nov 2026 08:51 CST · covers Tue 3 Nov 08:30 → Wed 4 Nov 08:51 CST (24h 21m; 1 scheduled brief) · run 20261104T145152Z-0a1b
2 need you · 1 merged (1 owner-approved) · 0 blockers · omerta-core not refreshed

Needs you
  [waiting]  Still waiting on you: cosmic_ac #46 merge (signed off), project-manager #287 spec approval.
           → #46 (3d 23h) · report · #287 (2d 18h) · spec

cosmic_ac
  [resolved]  #47 HEALPix mask support: review is running again (iteration 1).  → #47
  [merged · owner-approved]  #50 Speed up map smoothing.  → #50 · report
  [now]  1 in progress, 1 in review, 1 in QA, 1 at sign-off, 4 pending; CMB pipeline 8/12 merged.

project-manager
  [now]  No material change.

omerta-core
  [unavailable 2d]  Still not refreshed: project.yaml does not parse.

Delivered on attempt 3; attempts at 08:31 and 08:37 failed: No space left on device.
Feedback: pm brief feedback · Guidance: pm brief guidance show
```

- **Nothing lost or duplicated.** #50's merge notice appears exactly once,
  here. The two failed attempts left no brief, no receipt and no boundary
  change. Thursday's brief (B4) does not repeat it.
- **Delivery failures are visible.** They show in this brief's footer, in
  `pm brief status`, and as a sticky line in the hub TUI log.

---

## B4 — Unchanged interval, Thu 5 Nov 2026 08:30 CST

```text
Owner brief "owner" · 3 projects · no material change
As of Thu 5 Nov 2026 08:30 CST · covers Wed 4 Nov 08:51 → Thu 5 Nov 08:30 CST (23h 39m; 1 scheduled brief) · run 20261105T143000Z-1e2f
2 need you · 0 merged · 0 blockers · omerta-core not refreshed

Needs you
  [waiting]  Still waiting on you: cosmic_ac #46 merge (signed off), project-manager #287 spec approval.
           → #46 (4d 23h) · report · #287 (3d 18h) · spec

  [now]  No material change in cosmic_ac or project-manager.
  [unavailable 3d]  omerta-core still not refreshed: project.yaml does not parse.

Feedback: pm brief feedback · Guidance: pm brief guidance show
```

This is four lines, and every still-actionable item keeps its age.

---

## B5 — Catch-up after missed intervals, Mon 9 Nov 2026 08:30 CST

The TUI was down from Thu 12:00 to Mon 08:10, so the Fri 08:30 slot was missed.
At 08:11 a catch-up became possible less than 1 h before the 08:30 slot, so it
waited and covered both slots (impl R8).

```text
Owner brief "owner" · 3 projects
As of Mon 9 Nov 2026 08:30 CST · covers Thu 5 Nov 08:30 → Mon 9 Nov 08:30 CST (4d; 2 scheduled briefs; catch-up — pm was not running at Fri 08:30) · run 20261109T143000Z-5a6b
2 need you · 7 merged (4 auto, 3 owner-approved) · 0 blockers · all projects refreshed (omerta-core partial)

Needs you
  [waiting 7d 18h]  project-manager #287: spec still waits for your approval.  → #287 · spec
  [waiting 1d]  cosmic_ac #48 Notebook: lensing tutorial is signed off and held for your merge.  → #48 · report

cosmic_ac
  [merged · owner-approved] [resolved]  #46 Refactor plotting helpers; its wait for your merge is closed.  → #46 · report
  [merged · auto]  #51 Add beam deconvolution step.  → #51 · report
  [merged · auto]  #52 Vectorize mask application.  → #52 · report
  [merged · owner-approved]  #53 Update CAMB to 1.5.8.  → #53 · report
  [now]  1 in progress, 0 in review, 1 in QA, 1 at sign-off, 1 pending; CMB pipeline 10/12 merged.

project-manager
  [merged · owner-approved] [merged · auto]  2 merged: #143 Session cleanup for stale containers and push proxies; #217 terminal-status PRs drop their windows.
           → #143 (owner-approved) · #217 (auto) · reports
  [now]  No other material change.

omerta-core
  [resolved]  Refreshed again (project.yaml fixed Sat); live run state unavailable (no TUI).
  [merged · auto]  #12 Pin libp2p to 0.53.  → #12 · report
  [now]  First readable data: 3 in progress, 1 in review, 5 pending; later briefs report changes from here.

Guidance not followed: "Mention when a PR touching containers merges" (project-manager) — the input has no file or area
information; #143 is mentioned because its title names containers, but other container changes cannot be detected yet.
Feedback: pm brief feedback · Guidance: pm brief guidance show
```

- **Bounded.** Four days of events fit in 16 lines. cosmic_ac's guidance asks
  for one line per merge, and the composer followed it; the whole brief ran a
  little over the "about 15" soft target, well under the hard cap of 40.
- **Required items stay in.** #48 is a "Notebook:" PR but is waiting on the
  owner, so the cosmic_ac guidance's own exception keeps it in.
- **Mixed merge modes.** project-manager's mixed-mode merge line carries one
  label per distinct mode (impl §1.5). The links section and the Details
  appendix show which PR merged which way: `#143 (owner-approved) · #217
  (auto)`.
- **Data limits are stated.** "Guidance not followed" states plainly what the
  data cannot support (impl E9).

---

## B6 — Pause and resume, then a guidance rollback (Wed 11 Nov 2026 08:30 CST)

- **Mon 9 Nov 09:31.** The owner rolled the whole-brief guidance back to the
  setup version ([`conversations.md`](conversations.md) §3).
- **Mon 17:00.** The owner said "pause the brief until Wednesday, I'm
  travelling" and the agent ran
  `pm brief pause --quote "pause the brief until Wednesday, I'm travelling"`.
- **Wed 07:50.** The owner resumed it.
- **Tue 08:30.** This slot fell while paused and was skipped.

Workflow state, captured before the pause (Mon 16:59) and after the resume (Wed
07:51) by the QA harness this spec proposes (impl §14 scenario 9). Everything is
identical; brief pause/resume touches only `~/.pm/briefs/owner/{config,config-journal}.json*`:

| Checked | Before pause | After resume |
|---|---|---|
| sha256 of each `pm/project.yaml` (3 projects) | `9f2c…`, `41ab…`, `c07e…` | `9f2c…`, `41ab…`, `c07e…` |
| `pm autostart status --json` (`targets`, `runs[].state`) | identical | identical |
| `~/.pm/runtime/**` | identical | identical |
| tmux window lists | identical | identical (no `brief-owner` window created while paused) |

```text
Owner brief "owner" · 3 projects
As of Wed 11 Nov 2026 08:30 CST · covers Mon 9 Nov 08:30 → Wed 11 Nov 08:30 CST (2d; 2 scheduled briefs; 1 skipped while paused) · run 20261111T143000Z-9c0d
1 needs you · 1 merged (1 owner-approved) · 0 blockers · all projects refreshed (omerta-core partial)

project-manager
  [waiting 9d 18h]  #287: spec still waits for your approval.  → #287 · spec
  [now]  No other material change.

cosmic_ac
  [merged · owner-approved]  #48 Notebook: lensing tutorial.  → #48 · report
  [now]  1 in progress, 1 in QA, 1 pending.

omerta-core
  [now]  No material change (live run state unavailable: no TUI).

Guidance changes since the last brief
  [guidance]  Whole brief rolled back to the 1 Nov setup version: needs-you items lead each project again (your request, Mon).

Guidance not followed: cosmic_ac asks to leave out "Notebook:" PRs, but every merge is always listed (#48).
Feedback: pm brief feedback · Guidance: pm brief guidance show
```

- **The rollback shows.** There is no cross-project "Needs you" list any more,
  and needs-you items lead each project.
- **Required merges stay in.** #48's merge is listed even though cosmic_ac's
  guidance leaves "Notebook:" PRs out, because merges are required. The footer
  says why.

---

## B7 — Restart cases (Thu 12 Nov 2026), from `pm brief status`

**(a) TUI restart while the composer is writing.**

```text
$ pm brief status --name owner          # 08:31:30, TUI restarted at 08:31:10
brief "owner" · hub project-manager · schedule active · weekdays 08:30 America/Chicago
boundary: Wed 11 Nov 08:30 CST (run 20261111T143000Z-9c0d)
in flight: run 20261112T143000Z-3b4c · composing since 08:30:04 (window brief-owner alive) · timeout 08:50:04
last failure: none
$ pm brief status --name owner          # 08:32:40
boundary: Thu 12 Nov 08:30 CST (run 20261112T143000Z-3b4c) · published 08:32:21 · composer: draft (1 attempt)
in flight: none
```

The composer's tmux window survived the TUI restart and published normally. The
restarted TUI re-armed its timer, and its first tick saw the run still in flight
and did nothing.

**(b) Crash between delivery and commit** (fault injected in QA: `kill -9` of
`pm brief publish` right after the `latest.html` rename).

```text
$ pm brief status --name owner          # 08:33:05
boundary: Wed 11 Nov 08:30 CST (run 20261111T143000Z-9c0d)
in flight: run 20261112T143000Z-3b4c · RECEIPT PRESENT, not committed
$ pm brief tick                         # next timer tick, 08:33:30
brief "owner": rolled forward run 20261112T143000Z-3b4c (receipt present); boundary now Thu 12 Nov 08:30 CST
```

No second brief was produced, and Friday's brief starts at Thu 08:30.

---

## B8 — Composer failure: pm's plain brief, Fri 13 Nov 2026 08:30 CST

The composer window exited before publishing (the provider returned an error).
After 20 minutes without a receipt, the run was abandoned. The next tick
re-prepared and published pm's plain brief straight away. The plain brief uses
P1's default shape and **does not apply free-text guidance**, which only the
composer can interpret. The footer says so.

```text
Owner brief "owner" · 3 projects
As of Fri 13 Nov 2026 08:51 CST · covers Thu 12 Nov 08:30 → Fri 13 Nov 08:51 CST (24h 21m; 1 scheduled brief) · run 20261113T145104Z-6d7e
1 needs you · 1 merged (1 auto) · 0 blockers · all projects refreshed (omerta-core partial)

project-manager
  [waiting 11d 18h]  #287 Scheduled concise multi-project progress and change briefs: spec waits for your approval.  → #287 · spec
  [now]  9 in progress · 36 in review · 6 in QA · 0 at sign-off · 389 pending.

cosmic_ac
  [merged · auto]  #54 Add CI job for notebook execution.  → #54 · report
  [now]  1 in progress · 0 in review · 1 in QA · 0 at sign-off · 0 pending.

omerta-core
  [now]  No material change. Live run state unavailable (no TUI for pm-omerta_core-1b2c3d4e).

Plain brief (composer not used): composer window exited before publishing (claude exit 1) at 08:31; guidance not applied this time.
Feedback: pm brief feedback · Guidance: pm brief guidance show
```

---

## Dashboard banner (hub `pm pr dashboard`, R9)

This is added above the existing PR table. The rows and columns are unchanged.

```text
Owner brief "owner" — as of Fri 13 Nov 2026 08:51 CST · 1 needs you · open latest · history (8)
```

`open latest` links to `briefs/owner/latest.html`. `history` links to
`briefs/owner/index.html`, newest first, one line per published run with its
headline.
