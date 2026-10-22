# Open implementation questions

These questions are recorded for the two refactoring PRs. Both depend only on this PR, and neither depends on the other. Their scope is decided after the mockups are reviewed.

Answer each question from the actual code. Do not read the order or wording here as a preferred architecture. "No refactor needed" is an acceptable answer to any of them.

## PM actions-picker sharing (pr-e5873d7)

### Session directory and identity

1. **Enumerating sessions.** What PM state can list every session in the [inventory](session-inventory.md) with role, identity and live state, as a single question rather than per window? Known gaps:
   - QA helper ids exist only in `qa_resume.json`.
   - Planner and finalize session ids are not persisted.
   - Sign-off has no runtime_state entry.
   - Meta, ad-hoc panes and the tmux impl path keep no resumable Claude id.
2. **Stable identity.** What identifies a session across window recreation (review-loop iterations, watcher iterations, QA worker relaunches without the refiner pane) and across QA runs, whose scenario numbers are unique only per `loop_id`? How is "verified" exposed? Today it is a decorated verdict string, not a field.
3. **Ended sessions.** What does PM retain (transcript path, verdict, timestamps) so an ended session stays listed and readable?

### Open versus start

4. **Side-effect-free open.** Several picker actions mutate state when chosen:
   - `pr review` sets `in_review`.
   - `pr signoff` moves qa → sign_off.
   - The merge row runs `pr merge --resolve-window`.
   - `zz t` toggles the QA loop.

   What path lets a remote surface open an existing session without these effects, while the terminal picker keeps its current behavior?
5. **Starting with named side effects.** Can the effects a confirmation must state (status change, merge attempt, loop restart, fresh relaunch) come from the same place as the picker's action definitions, so they cannot drift?
6. **Duplicate prevention across processes.** `pr start` and `pr review` do find-then-create without a lock, `start_qa` checks only the in-process loop, and ad-hoc roles are checked per window. How does a repeated or concurrent request from a remote surface join a pending start rather than create a second worker? What request identity is used, and how is "starting" visible?

### Documents and approval

7. **Version identity.**
   - `spec_pending` stores only `{phase, generated_at}`.
   - `approve_spec` clears it without checking content.
   - The spec can be rewritten in the PR workdir while review is pending (`spec_gen.get_spec` lookup order).

   Where is the content hash recorded when review starts? Can approval require the expected hash and refuse a mismatch (D03), so a changed spec never inherits approval?
8. **Revision requests.** `reject_spec` regenerates the spec with appended feedback. Conversation in the impl session revises it in place (A08–A09). Which is the PM-sanctioned path for a remote "request changes", and how is the new version announced?
9. **Plan approval.** PM has no plan approval state today. What should approving a plan version mean (for example: record it, load PRs, start auto-start), or should plans have discussion only? D02 marks this PROPOSED.
10. **Hand-back.** After an approval, what guarantees that nothing else needs a human until a configured hold? Answer against pr-3ae2fc3's spec-review pauses and autostart's `--wait-for-merge`.

### Status, history and gates

11. **History and timers.** Can the glasses use pr-8020495's query and presentation model as it is? The design needs:
    - timers with "unknown"
    - holds with no countdown
    - attempts per QA scenario
12. **Needs you.** Which PM states feed the root list: pending spec/plan reviews, INPUT_REQUIRED sessions (including a refiner reject), manual merge holds, failures? Is there one source, or are several queries combined?
13. **Merge from a remote surface.** With pr-ac10f03, the merge gate binds approval to HEAD and base. What must a "Merge now" request carry (expected HEAD), and how is a refusal reported back with its routing (sign-off reruns, hold stays)?

### Sessions and transport

14. **Reaching a session's conversation.** Options observed:
    - read Claude transcripts and hook events, and inject messages the way `notify_spec_approved` does on pr-3ae2fc3
    - Claude Remote Control plus an Even Terminal connector, as Pageborne does (session names: pr-3a8111d)
    - something else

    Which preserves PM's existing ownership of the pane?
15. **Messages to automated sessions.** Can a user safely message a verifier, refiner or review-loop session (B07)? What happens to verdict detection (idle-prompt hooks, transcript parsing) when a human turn is inserted? Should such sessions be read-only by default?
16. **Transport and origin.** Even requires exact HTTPS origins plus CORS, and PM's dashboard binds `127.0.0.1`. What endpoint and authentication would a release glasses build use? Consider the Tailscale identity Pageborne's web companion uses, and validated requests with no GET mutations.
17. **Freshness.** Should the phone poll or stream with a resumable cursor? How is data age reported for the reconnect banner?

## Pageborne sharing (pr-9374887)

1. **Where the experience lives.** Is PM review:
   - a separate Even Hub app,
   - a mode or "library" inside Pageborne, or
   - Pageborne documents with PM-aware sessions?

   Consider one package per app, switching apps on the glasses, shared speech models (about 586 MB of WebGPU weights) and per-build network origins.
2. **Reading behavior to share.** Which of Pageborne's reading behaviors should PM documents get, and how? Candidates:
   - pagination and native-text layout
   - footer layout
   - position retention across edits
   - table formatting
   - the serial display lane
   - SDK storage persistence
3. **Voice.** Should PM reuse Pageborne's hold-to-speak, review and on-device STT (vocabulary hints from the current passage), use a remote speech provider, or have no voice? What about memory pressure alongside PDF preparation?
4. **Session linking.** Pageborne binds per-document sessions through Even Terminal (Codex daemon; the native Claude connector is attach-only). Can PM's tmux-hosted sessions be attached the same way? If so, what replaces Pageborne's per-paper workspace and file transfer for PM plans/specs, which already live in the repo?
5. **Version snapshots.** Pageborne attaches an immutable document snapshot per question (0.8.113). Is that the mechanism for PM's "message carries version and hash", or does PM's content hash suffice?
6. **Companion.** How would PM's companion views (full spec, diff, typed reply, confirmation) coexist with Pageborne's phone UI (library drawer, Ask panel, dock) if they share an app?
7. **Test harness.** Can PM's evidence reuse Pageborne's simulator recorder (`scripts/simulator-test.mjs --record`) and browser suites, or is this PR's capture script enough?
8. **Preservation.** Which Pageborne flows must be re-verified on their existing surfaces if anything is shared? Candidates:
   - reading modes
   - Ask with Claude and Codex
   - Librarian
   - library sync
   - release/debug builds

## For the implementation PR (pr-1e0772a)

1. **Hardware validation.** Which of the items listed in [constraints](constraints.md#needs-hardware-validation-not-established-here) hold on G2 glasses and the R1 ring, and which of them change the design?
2. **The live journey.** Does the journey hold against real PM state: a document changed during review, reconnection, review and manual merge holds, history, and repeated inputs?
3. **Reproduction.** Which exact cross-repository revisions and setup (PM, Pageborne, Even Terminal or any bridge) does someone need to reproduce it?
