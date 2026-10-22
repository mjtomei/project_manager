# pr-9e7847d — Even Realities plan/spec review: interface constraints and demo screenshots

Design-only PR. Deliverables are documents, a runnable mockup and screenshots
taken with the official Even Hub simulator. No production PM or Pageborne code
changes.

Scope sources:
- The PR description on master `e4d6353d`, including the session-access
  paragraph added at the user's request mid-session.
- The user's message stating that every session the current PM actions panel
  exposes must be reachable on the glasses, including each QA scenario and its
  helper sessions.

## Inputs reviewed

| Input | Where | Notes |
|---|---|---|
| Even Hub SDK `@evenrealities/even_hub_sdk@0.0.16` | npm; README + `dist/index.d.ts` | Container model, events, limits |
| Even Hub docs (hub.evenrealities.com/docs, fetched 2026-10-21) | build/display, page-lifecycle, device-apis, contextual-menu, background-lifecycle, networking, app-submission, FAQ, simulator | Cited per constraint |
| `@evenrealities/evenhub-simulator@0.9.5` (+ `sim-linux-arm64`) | npm | Runs headless here under Xvfb + dbus; automation API on `--automation-port` |
| `@evenrealities/pretext@0.1.4` | npm | Firmware font metrics: 27 px line height, per-glyph advance widths, glyph availability |
| `@evenrealities/even-terminal@0.10.5` / `0.8.1` | npm | Desktop session bridge used by Pageborne Ask |
| `mjtomei/even-terminal-patch` | GitHub (public) | Shared Codex/Claude Remote Control attachment |
| Pageborne source snapshot | `/tmp/pm-design-context/pageborne-source` | Copied by the user from `/home/matt/even/reader` at upstream HEAD `4d769f60a77ab38ae327d715db777a702e8fb2bd`. 294 files; hashes in `SNAPSHOT-MANIFEST.json`. Excludes runtime config, `.env`, state, private library, git metadata, dependencies, builds and model weights. **Not committed to PM**; only provenance and citations are recorded. |
| PM actions panel + related windows | `pm_core/cli/session.py`, `pm_core/qa_loop.py`, `pm_core/tui/*`, `pm_core/spec_gen.py`, `pm_core/cli/plan.py`, `pm_core/runtime_state.py` | Session inventory below |
| In-flight PM branches | `pm/pr-8020495` (history/timers), `pm/pr-3ae2fc3` (spec-review pauses), `pm/pr-ac10f03` (sign-off integration) | None merged into master at `e4d6353d`. pr-ac10f03 merged later (`b876dbcb`); the audit stays pinned to `e4d6353d` and its `session.py` references are unchanged on master |

## 1. Requirements (grounded)

**R1. Glasses constraints document.** Record the constraints affecting:
- document readability
- navigation/input
- updates
- feedback
- connection lifecycle
- glasses versus companion (phone WebView) behavior

Each constraint gets a citation and one of these labels: verified from docs, verified from SDK source/types, verified in the official simulator in this PR, verified by Pageborne's own evidence, community-reported, or assumption. The constraints come from the SDK types, the docs, pretext metrics and Pageborne's documented hardware findings. Examples:
- 576×288 canvas.
- 27 px rows, so 9 body rows plus a footer row.
- At most 8 text containers per page, and 12 containers in total.
- About 999 bytes per text container in the simulator.
- No opaque fill: black is transparent, so overlays must displace content.
- One event-capture container.
- Double tap on the root page must open the system exit dialog.
- Tap-then-hold belongs to the OS menu.
- No speech-to-text in the SDK.
- WebView suspension (Android cold start, dev builds die on background).
- Network origins must be whitelisted.

**R2. Concise interaction proposal.** It must define user-facing behavior in terms of intents and must not prescribe layout or gestures. The mockup shows one candidate binding and is labelled as such. First-class flows:
- (a) Long-form reading of a plan or spec, with identity and version on screen.
- (b) Discussion in the document's associated existing PM session:
  - impl spec → the PR's impl session (`#N` window)
  - qa spec → the QA planner (`qa-#N`, role `qa-planner`)
  - plan → `plan:review:<plan>` (or the add/breakdown session that owns it)
- (c) Revision request, then re-review with "what changed".
- (d) Explicit approval of a specific version. Approval hands work back to unattended PM execution; existing holds such as manual merge stay explicit.

The proposal must also cover:
- Reading context (position and version) retained across document ↔ discussion moves.
- A changed document distinguished from the version under review.

Supporting flows:
- PR selection
- action/status navigation
- history/timers (pr-8020495 semantics)
- manual-merge waits
- busy, error and reconnect states

**R3. Session-access parity with the PM actions panel and related windows (added requirement).** The glasses must be able to select and switch to each of these sessions:
- impl (`#N`)
- review (`review-#N`, including the review-loop iteration)
- sign-off (`signoff-#N`)
- existing merge/recovery (`merge-#N`; after pr-ac10f03 only the post-publish pull recovery)
- QA planner (`qa-#N` role `qa-planner`)
- QA interactive `qa-#N-s0`
- every scenario `qa-#N-sK`, with its refiner (`qa-concretize-sK`), execution worker (`qa-scenario-sK`) and verifier (`qa-verify-sK`) where present
- QA finalize where present
- the plan/project sessions PM exposes: plan add/breakdown/review/deps, meta, guide, watchers, ad-hoc Claude panes

Each row shows role, PR/scenario identity and current state. Requirements for the demo:
- It opens a particular QA scenario and its verifier.
- It inspects or discusses the ongoing work.
- It returns to the originating document or session list without launching a duplicate.
- An aggregate QA status page, or only document-linked chats, is insufficient.

**R4. Runnable mockup and simulator screenshots.**
- The mockup is a small static Even Hub web app using the real SDK and pretext metrics, fed by an explicitly simulated PM backend.
- A capture script launches the official simulator, drives real simulator inputs (`/api/input`) plus labelled simulated PM events, and saves 576×288 glasses screenshots, along with a few companion WebView screenshots.
- Every screenshot is labelled SIMULATED, with its scene id and the simulator version.
- A constraint checker runs on every frame (bytes, container counts, row budget, measured widths) and the capture fails on a violation.

**R5. Open implementation questions** for pr-9374887 (Pageborne sharing) and pr-e5873d7 (PM actions-picker sharing), recorded separately. They must not prescribe components, packages, APIs or extractions.

**R6. Easy to inspect from PM's report.**
- Committed under `pm/docs/even-realities/`: proposal, constraints, session inventory, open questions, Pageborne provenance, mockup source, screenshots and a static `index.html` gallery.
- The gallery is also copied to `/pm-captures/even-realities/`, the PR captures directory the per-PR `report.html` and dashboard serve, so sign-off can link it.
- A PR note points sign-off at the gallery.

**R7. No production refactor.** Nothing under `pm_core/` changes, and nothing is written to the Pageborne repository. The Pageborne snapshot is not committed. The dependency graph stays as it is:
- pr-9374887 and pr-e5873d7 each depend only on pr-9e7847d.
- pr-1e0772a depends on both.
- Manual merge of this PR is the design checkpoint.

## 2. Implicit requirements

- **Version identity must be content-based.** On master, `spec_pending = {phase, generated_at}` (`spec_gen.py:generate_spec`). `approve_spec` clears it without checking content (`spec_gen.py:369-407`), and `pm pr spec-approve` approves whatever file is on disk when the editor closes. The spec file lives in the PR workdir, which the impl session can rewrite while review is pending (`spec_gen.get_spec`, lookup 1).
  - The design therefore shows approval bound to the content hash that was displayed. A change between viewing and confirming refuses the approval.
  - This is recorded as a PM open question rather than assumed to exist.
- **No plan approval gate exists in PM today.** The plan journey shows "approve" as **proposed** behavior, labelled as such. What approval triggers (e.g. `plan load` + autostart) is an open question.
- **Picks with side effects must not happen by navigation.** These existing picks mutate state:
  - picking merge attempts the merge (`pr merge --resolve-window`)
  - picking review moves status to `in_review`
  - picking sign-off moves qa → sign_off
  - `zz t` toggles the QA loop
  - `zz d` restarts the review loop

  The glasses design keeps "open existing session" separate from "start/restart action". Start/restart requires an explicit confirmation that names its side effects.
- **Session identity:**
  - QA scenario numbers are unique only within a run (`loop_id`), so the UI shows run identity alongside scenario numbers.
  - Review-loop and watcher windows are recreated per iteration, so identity is role + PR + iteration, not pane id.
- **Sign-off has no live runtime badge** (no runtime_state writer). The mockup shows the state PM can actually derive (window open, `pr.signoff` verdict) and records the gap.
- **Duplicate prevention:** repeated taps coalesce to one request. A pending launch shows as "starting", and a running session is opened rather than relaunched. PM's own races (`pr start`/`pr review` unlocked find-then-create; `start_qa` checks only the in-process loop) are recorded as open questions.
- **Reading/discussion context:**
  - Sending a message attaches document identity, version and position, as Pageborne attaches an immutable snapshot per question (README 0.8.113).
  - Returning restores the exact page.
  - Sending never auto-retries ambiguously.
- **Transparency:** glasses text containers have no background. Popups and listening panels must shrink the body rather than overlay it (Pageborne `glasses.js` transcription geometry).
- **Mockup isolation:** the simulated backend never contacts a real PM, tmux or agent, and the mockup has no network origins beyond its own static server.
- **Reproducibility:** pin exact package versions (`package-lock.json`). Do not commit `node_modules`.

## 3. Ambiguities and resolutions

1. **"Review the existing Pageborne app" when the repo was not mounted.** Resolved: the user copied a snapshot to `/tmp/pm-design-context/pageborne-source` (HEAD `4d769f60`). Its provenance is recorded and it is not committed.
2. **"Without presupposing a layout or gesture scheme" versus runnable mockups.** Resolved:
   - The proposal states behavior as intents: next/previous, choose, back, speak, more actions, and confirm.
   - The mockup uses one illustrative binding consistent with Pageborne and Even guidelines: swipe moves/pages, tap chooses or opens actions, double tap goes back (system exit on root), hold speaks, and tap-then-hold opens the OS menu.
   - The binding is labelled as a candidate.
3. **What "approve" means for plans.** Resolved: shown as a proposed explicit approval with a stated effect; flagged as an open PM question.
4. **Which session a document's discussion belongs to.**
   - impl spec → PR impl session
   - qa spec → QA planner session for the current run
   - plan → plan review session (`plan:review:<id>`)

   If that session is not running, the user is offered "Start discussion session" with its side effects; nothing launches silently.
5. **Glasses as the dispatch surface for merge.** Resolved:
   - Manual merge waits are displayed.
   - "Merge now" is offered only behind a confirmation that names the sign-off-approved HEAD.
   - PM's merge gate stays authoritative, and a refusal is shown as such.
6. **Version numbering.** PM has no spec versions. The design shows a short content hash plus a per-review sequence number ("v3 · 7f3a") derived from observed hashes; the open questions cover where PM would record it.
7. **Screenshot source.** Official simulator `0.9.5` under Xvfb on this arm64 host. Verified working: SDK page creation, text upgrades, and input events delivered from `/api/input`. Fidelity caveats are documented: font, list scrolling, no status events, and no Bluetooth or physical refresh.

No **[UNRESOLVED]** items remain. Pageborne access was resolved with the user.

## 4. Edge cases to show or record

- The document changes while reading: a banner appears, the reader stays on the reviewed version, and "what changed" is available.
- The document changes between pressing approve and confirming: the approval is refused.
- A revision request is answered by a new version, followed by re-review.
- The linked session is busy: the message is queued in the same session, never a second session (Pageborne 0.8.112 behavior).
- The linked session is not running: an explicit start, with side effects named.
- QA scenarios:
  - a scenario's refiner rejects (INPUT_REQUIRED, no worker)
  - a worker is relaunched (refiner pane gone; retry count shown)
  - a verifier is FLAGGED and retries
  - scenarios are queued beyond `qa-max-scenarios`
  - a second QA run with renumbered scenarios
- Selecting a session whose window vanished: shown as ended, with its transcript available if PM has one; no auto-relaunch.
- Repeated taps on Start: coalesced, showing "starting…"; the second tap opens it when ready.
- Connection:
  - phone WebView suspended (data shown with its age)
  - PM host unreachable (↔ after repeated failures, as in Pageborne's three-failure rule)
  - glasses disconnected
  - reconnect restores the same place
  - a pending message is not resent
- Manual merge hold: re-signing does not release it (pr-ac10f03); "Merge now" refused because HEAD changed after sign-off.
- Root-page double tap must open the system exit dialog (submission rule).
