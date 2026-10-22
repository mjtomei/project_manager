# pr-9e7847d QA spec: Even Realities plan/spec review design checkpoint

This PR delivers design material and no production code. It has four parts:
- Docs in `pm/docs/even-realities/`: proposal, constraints, session inventory, open questions and Pageborne provenance.
- A runnable mockup in `pm/docs/even-realities/mockup/`:
  - a browser preview server with a `/director` queue of simulated events
  - a DOM-free controller
  - a phone companion panel
  - `check`, `capture` and `gallery` scripts
- A screenshot gallery (`index.html`), also copied to the PR captures dir as `even-realities/index.html`.
- Edits to `pm/project.yaml`: this PR's description and note, plus three follow-up PR descriptions.

`pm_core/` is not touched.

The user-facing surfaces are:
1. the **browser preview**, from `npm run serve` (glasses mirror canvas, keyboard intents, demo buttons and companion panel);
2. the **mockup CLI**: `npm ci --ignore-scripts`, `npm run check`, `npm run capture` and `npm run gallery`;
3. the **review gallery and docs**, opened by a reviewer from the repo or from PM's captures dir;
4. **pm itself** reading the edited `project.yaml`.

## 1. Requirements

### Browser preview: the reading/discussion/approval journey
- **R1** Given the preview is freshly served, when the user opens it, then:
  - the mirror shows "Needs you" with #214 impl spec v2, the plan review, a QA scenario needing input and a #211 manual merge;
  - the companion shows "SIMULATED PM data".
- **R2** Given Needs you, when the user selects the #214 impl spec, then the reader opens at page 1. The footer shows the document identity, `v2 · review · 1/5`.
- **R3** Given the reader, when the user pages forward and back, then pages advance and return one at a time. The position indicator updates and no content is clipped. The problems area stays empty.
- **R4** Given a document page, when the user holds to speak and releases with a simulated utterance queued, then a review panel names the target session (#214 impl) and offers Send, Speak again and Cancel. The document stays visible above it.
- **R5** Given the review panel, when the user sends, then the footer says "Sent to #214 impl". The view stays on the same page. The session transcript (companion) shows the message with its context label: document, version, hash, section and page.
- **R6** Given a document, when the user opens document actions and chooses Discuss, then the existing #214 impl session opens with a notice that it was opened, not launched. No new session appears.
- **R7** Given the discussion session, when a simulated revision v3 is published and the user goes back, then the reader returns to the same v2 page and shows a "Changed: v3 · you are reading v2" banner. It does not jump to v3.
- **R8** Given v2 is no longer current, when the user opens document actions, then approval is blocked ("read v3 first") and "What changed" is offered.
- **R9** Given What changed, when the user picks an item, then v3 opens at that item and the footer shows v3 under review.
- **R10** Given the user is reading v3, when they choose Approve and confirm, then the confirmation names v3 and its hash and states the consequences (unattended phases, manual merge). Confirming leads to an "after approval" progress view where only the merge hold needs the user.
- **R11** Given the companion panel on a session, when the user types a message and submits, then it is sent once to that session with the same reading context. Pressing Enter in the text field does not also trigger a glasses "select".

### Browser preview: session access
- **R12** Given the PRs list, when the user opens #215 and then its sessions, then implementation, review (with iteration), the QA run and sign-off are listed, each with a state glyph and text.
- **R13** Given #215 QA run 2, when the user opens it, then the planner, the interactive s0, every scenario with its own state (verifying, needs input, retrying, queued) and finalize are listed.
- **R14** Given scenario s2, when the user opens its verifier, then the session header names the PR, run, scenario, role and state. The notice says "Opened existing … · nothing launched".
- **R15** Given the busy verifier, when the user speaks and sends, then the message is "Queued in … (busy) · same session". No second verifier appears.
- **R16** Given a session, when the user uses session actions to switch to the scenario's worker and then chooses "Return to #215 QA spec", then the QA spec reopens at the page they left. No duplicate sessions are created anywhere.
- **R17** Given scenarios s3 and s4, when the user opens them, then:
  - s3 shows the refiner's REJECT and needs input, and also appears in Needs you;
  - s4 shows "pane gone" for its relaunched refiner and explains that the verifier comes on first PASS.
- **R18** Given a queued scenario, when the user selects it, then a notice says it is queued and PM will launch it. No session view opens.
- **R19** Given sign-off is not running, when the user selects it, then a confirmation names the side effect (qa → sign_off).
  - Confirming shows "◐ starting".
  - Selecting it again says "Already starting".
  - After the simulated "sign-off started" event, selecting it opens the running session.
- **R20** Given the OS menu items, when the user chooses Plans and project, or Sessions, then plan, meta, guide and watcher sessions, or all PR sessions, are listed with states. Lists longer than one screen scroll and show their position.

### Browser preview: status, history, holds and connectivity
- **R21** Given PRs and status, when the user opens #216 history, then PR-owned timers show their owner and what fires next ("unknown" where applicable), plus recent attempts.
- **R22** Given #211 (manual merge hold), when the user opens history, then the hold shows "no countdown".
- **R23** Given the #211 merge confirmation, which names HEAD and base, when the head moves (simulated) and the user confirms, then the merge is refused as PM's decision, the hold stays, and #211 is not merged.
- **R24** Given a document is open, when the connection drops (simulated), then a "Reconnecting to PM · data N old" banner appears and reading continues.
- **R25** Given the connection is down, when the user sends speech (or types on the phone), then "Not sent: PM unreachable · nothing queued" appears.
- **R26** Given reconnect, then "Reconnected · same place · nothing resent" appears. The view is unchanged and no earlier refused message appears in the transcript.
- **R27** Given the root view, when the user presses back, then the footer explains that a double tap opens the system exit dialog. The app does not exit or crash.
- **R28** Given the plan review (plan-sync v4), when the user starts approval, then the confirmation labels it PROPOSED. If the plan changes (v5) before confirming, confirming yields "Not approved" with What changed showing #218.

### Mockup CLI
- **R29** Given a fresh checkout, when the user runs `npm ci --ignore-scripts` and `npm run check`, then it prints `54 screenshots, N frames checked, 0 failure(s)` and exits 0. `check A` (one journey) and `--quiet` work.
- **R30** Given the simulator dependencies are installed, when the user runs `npm run capture --out <dir>` and then `npm run gallery`, then:
  - 54 glasses PNGs, X01 and 3 phone shots are written with a manifest;
  - capture reports 0 problems;
  - the gallery lists every shot with a SIMULATED tag.
- **R31** `npm run serve` binds to 127.0.0.1:5180 and serves the mockup. A malformed director POST returns 400. Path traversal or a bad path returns 404/400.

### Review deliverable
- **R32** Given the gallery (repo copy and captures-dir copy), when the reviewer opens it, then:
  - every image loads;
  - every doc link resolves;
  - each card has an id, title, SIMULATED tag, caption, scene and steps;
  - the phone shots are shown;
  - the page has no horizontal scroll at phone width and is legible in dark mode.
- **R33** Given the docs:
  - proposal shot ids (A01–D04, B01–B22, C01–C11, X01) exist in the gallery;
  - constraints carry source and verified/assumption labels;
  - the session inventory covers every role the PR description lists;
  - open questions are addressed to pr-e5873d7, pr-9374887 and pr-1e0772a without prescribing APIs.

### pm regression
- **R34** Given the edited `project.yaml`, when the user runs pm, then:
  - `pm pr list` and the TUI load;
  - pr-9e7847d shows its note;
  - pr-9374887, pr-e5873d7 and pr-1e0772a show their extended descriptions.

## 2. Setup
- Node ≥ 18 and npm. From the repo: `cd pm/docs/even-realities/mockup && npm ci --ignore-scripts`.
- Browser preview: `npm run serve`, then open http://127.0.0.1:5180/. Keys:
  - ↑/↓ = swipe
  - Enter = tap
  - Esc = double tap
  - hold A = speak
  - 1–4 = OS menu items
- Demo buttons and `curl -X POST /director -d '{"type":"pm","event":{...}}'` inject simulated events. Use `{"type":"speech","text":...}` before a hold/release to queue an utterance.
- The simulator capture needs `libwebkit2gtk-4.1-0 libgtk-3-0 libsoup-3.0-0 dbus dbus-x11 xvfb`, plus `ffmpeg` for labelled copies. Use `--out` to a scratch dir so the committed screenshots are not overwritten.
- pm: `./install.sh --local` if pm is not on PATH.

## 3. Edge cases
- **E1** Given a list view with no document or session, when the user holds to speak, then "Open a document or session to speak" appears and no panel opens.
- **E2** Given a voice review, when the user releases with no utterance queued, then the draft says "(no speech recognized)". Cancel or back says "Cancelled · nothing sent". Speak again re-listens.
- **E3** Given the "impl publishes spec v3" button is pressed repeatedly, when there are no scripted revisions left, then nothing crashes and the version stays v3.
- **E4** Given the user is on the confirm-approval screen for a version, when a revision is published before confirming, then confirming does not approve and offers What changed.
- **E5** Given a disconnect during a voice review, when Send is chosen, then the send is refused, not queued. After reconnect it is not resent.
- **E6** Given the OS menu is used from deep inside a session tree, when "Needs you" is chosen, then the stack resets to the root and back from there behaves as root back.
- **E7** Given two preview tabs and director POSTs, then both apply the same simulated events in order. A late-opened tab replays the queue from the start.
- **E8** Given port 5180 is already held by `npm run serve`, when `npm run capture` is run, then it fails clearly or uses the override ports. It must not silently drive the user's running preview.
- **E9** Given `npm run check` while the preview runs, then check is independent: it uses no ports and does not modify files.

## 4. Pass/fail criteria
- **Pass** requires all of the following:
  - every Then above is observable on the mirror, the companion, CLI output or the gallery;
  - the preview's problems area stays empty;
  - `check` exits 0;
  - capture reports 0 problems;
  - no action creates a duplicate session, sends a message twice, approves a superseded version, or merges past a refused gate;
  - `git status` is clean after `check`.
- **Fail** if any of the following happens:
  - a crash or uncaught error in the console;
  - a truncated or clipped footer hint;
  - a view switches on its own after a reply or revision;
  - approval succeeds for a non-current version;
  - a refused offline message appears later;
  - a gallery link is broken;
  - the screenshots lack the SIMULATED identification;
  - pm fails to load `project.yaml`.

## 5. Ambiguities
- The simulator is official and binary, so it may not run in every QA container. Resolution: capture is attempted. If the environment cannot run it, the scenario records why and verifies the committed screenshots and manifest instead. This is not a product failure.
- Hardware behavior (real G2/R1, Bluetooth, WebView suspension) is explicitly out of scope; it is deferred to pr-1e0772a.
- "report.html should link it": PM's QA finalize step writes report.html. QA verifies that the gallery exists in the PR captures dir and is openable, and that report.html (if one exists) links it.
- Layout and gestures are a candidate, not a requirement. QA checks behavior (identity, versions, no duplicates, explicit confirms), not exact rows or keys.
