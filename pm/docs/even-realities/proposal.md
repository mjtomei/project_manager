# Plan/spec review and PM sessions on Even Realities G2: interaction proposal

**Status:** design checkpoint for pr-9e7847d. Manual merge of this PR approves the behavior below. The refactoring PRs (pr-9374887 Pageborne, pr-e5873d7 PM actions picker) then decide how to deliver it, and pr-1e0772a implements it.

**Evidence:** [constraints](constraints.md) · [session inventory](session-inventory.md) · [open questions](open-questions.md) · [Pageborne snapshot](pageborne-snapshot.md) · [screenshot gallery](index.html), with ids like **A05**.

This document defines **behavior**. Layout and gestures in the mockup are one candidate that fits the constraints; they are not part of what is being approved.

## 1. The central journey

> Read a plan or spec → discuss it in the PM session it belongs to → request revisions and re-review → approve the exact version read → PM carries out the work unattended, with only configured holds asking for attention.

| Step | Required behavior | Shown in |
|---|---|---|
| Find work | A root view lists what is waiting for the user: specs and plans pending review, sessions that need input, manual merge holds. Each entry opens the right place directly. | A01 |
| Read | Long-form reading is paginated for the glasses and never relies on native scrolling. Every page shows document identity, version, review state and position. Pages keep items and headings together where they fit. | A02, A03 |
| Discuss | Discussion goes to the document's **existing** session: impl spec → that PR's implementation session, QA spec → that QA run's planner, plan → the plan's review session. Speaking from the page targets that session without leaving the page. If the session is not running, the user is offered an explicit start; nothing launches silently. | A04–A09 |
| Context travels | Each message carries document id, version, content hash, section and page, so the agent knows exactly what the user was reading. | A08 (`[#214 impl spec v2 4c1e · Ambiguities · p4]`) |
| Stay oriented | Moving between document and discussion keeps a navigation trail. Back returns to the same document version and page. From deep inside the session tree, one action returns to the originating document. | A10, B10, B15 |
| Revise | A revision from the session creates a new version. The open document **does not switch on its own**. It shows "Changed: v3 · you are reading v2", and approval of v2 is blocked. "What changed" lists changed and added items and opens the new version at each one. | A10–A13 |
| Approve | Approval is a distinct, confirmed action. It names the version and content hash shown and states the consequences: implementation resumes unattended, the automated phases follow, and merge stays manual if configured. | A14, A15 |
| Hand back | After approval the user sees PM progress without driving any agent window: implementation, review loop, QA, sign-off, then the remaining hold. | A16, A17 |

**Approval binds to content.**
- A document that changes between reading and confirming is not approved. The user is told so and offered what changed (D03).
- A changed document never inherits an earlier approval.
- Navigation, discussion and reading never count as approval.

**Plans.** PM has no plan approval gate today. The mockup labels plan approval **PROPOSED** (D02); its effect is an [open question](open-questions.md).

## 2. Every PM session, not just document chats

Everything the PM actions panel and its related windows expose is reachable. See the [session inventory](session-inventory.md).

| Required behavior | Shown in |
|---|---|
| A PR's sessions list implementation, review (with loop iteration), each QA run, sign-off, merge recovery when present, and ad-hoc Claude panes. Each row has a state. | B03 |
| A QA run lists the planner, the interactive session s0, **every scenario** with its own state (verifying, needs input, retrying, queued) and finalize (listed before PM launches it). A single aggregate QA entry is not enough. | B04 |
| A scenario lists its refiner, execution worker and verifier. Absent helpers say why: "pane gone" after a relaunch, "on first PASS", "not launched". | B05, B12, B13 |
| A session view states PR, QA run, scenario, role, title, pane role and live state, so parallel sessions stay distinguishable. | B06, B09, B11, B14 |
| Opening an existing session **attaches**; it never launches ("Opened existing qa-verify-s2 · nothing launched"). | B06, B11, B19 |
| The user can inspect ongoing work and speak to the session. A busy session queues the message in the **same** session. | B07–B09 |
| From any session: the scenario's other sessions, all of the PR's sessions, or return to the originating document. | B10, B11, B15 |
| Plan, meta, guide and watcher sessions are listed with the same state column. | B20–B22 |
| Starting a session that is not running needs confirmation naming PM's side effect (for example qa → sign_off). Repeated selections join the pending start; once ready, selection opens it. | B16–B19 |

## 3. PR status, history and holds

| Required behavior | Shown in |
|---|---|
| PR list with the state that matters: spec review, QA input, review loop, manual merge, pending/blocked. | C01 |
| PR view with current activity, holds, dependencies, its documents, sessions, history and available actions. | C02, C04, B01 |
| History and timers (pr-8020495 semantics):<br>• PR-owned timers with time left and what happens next, "unknown" when PM cannot tell.<br>• Indefinite holds show "no countdown".<br>• Recent attempts show elapsed time and outcome. | C03, C05 |
| A manual merge wait stays explicit. "Merge now" names the signed-off HEAD and base, and PM's gate re-checks both. A refusal is shown as PM's decision, with what happens next; the hold remains. | C04, C06, C07 |

## 4. Feedback, busy, error and reconnect

| Rule | Shown in |
|---|---|
| Feedback is in place: a one-line notice in the footer, state glyphs, and a banner row for document or connection state. Replies never switch the view. | A06, B08 |
| Messages are reviewed before sending and sent at most once. Busy sessions queue in place. | A05, B07, B08 |
| Connection loss shows "↔ Reconnecting to PM · data N old" after repeated failures. Reading continues from the local copy. | C08 |
| Actions while disconnected are refused, not queued for later ("Not sent: PM unreachable · nothing queued"). | C09 |
| Reconnect restores the same place and resends nothing. | C10 |
| Starting is shown as in progress ("◐ starting…") and repeated taps do not duplicate it. | B17, B18 |
| Root back hands off to the system exit dialog, as Even requires. | C11 |

**State glyphs** (all present in the firmware font): ◐ working · ○ idle · ● waiting for you · ? needs input · ! error · ■ done · □ ended/queued · ◆ approved · ◇ hold · ↔ reconnecting · ▶ cursor.

## 5. Intents and the candidate binding

The behavior is defined on six intents. The mockup binds them as Pageborne and Even's guidelines do.

| Intent | Candidate binding (G2 temple or R1 ring) | Notes |
|---|---|---|
| Next / previous | swipe down / up | Page, move cursor, scroll transcript |
| Choose | tap | Open item, document actions, confirm |
| Back | double tap | Must open the system exit dialog on the root page |
| Speak | hold, release to review | Review panel: Send / Speak again / Cancel |
| Go to | tap-then-hold opens the OS menu with app items: Needs you, Sessions, PRs and status, Plans and project | X01. The OS adds Display off, Brightness and Close |
| Confirm | choose on a confirmation screen | Approval, starts and merge are never one gesture away |

## 6. Glasses versus companion

The glasses carry the whole journey:
- read
- discuss by voice
- approve
- open any session
- see status

The phone page is the same app (Even Hub runs one WebView). It adds what the glasses cannot do well:
- full document text
- exact diffs
- typed messages
- detailed confirmations

It calls the same commands, and the glasses never require it to be visible. See the phone captures in the gallery for A10, A15 and B09.

## 7. What the mockup simulates

The mockup runs the real SDK in Even's official simulator. These parts are **simulated**:
- all PM state (fictional PRs #209–#217 and plan `plan-sync`)
- agent replies
- document revisions
- connection changes
- speech recognition

It contains no PM, tmux or agent integration, and it decides no transport, package or API. Every frame passes the container limits checked by `mockup/scripts/check.mjs`. Hardware validation remains for pr-1e0772a ([constraints](constraints.md#needs-hardware-validation-not-established-here)).
