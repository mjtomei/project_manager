# PM session inventory and glasses parity

Requirement: every session reachable from PM's actions panel (the popup picker, `prefix+P`) and its related windows must be reachable on the glasses. Each must be distinguishable by role, PR/scenario identity and state, and opening it must not start a duplicate.

This document records what PM exposes on master `e4d6353d`, and how the [mockup](index.html) lists each session.

Code references were read on that revision; line numbers are pinned to it. In-flight branches (none merged at the time) are noted where they change the panel. pr-ac10f03 has since merged (master `b876dbcb`); the `session.py` references below still hold there:
- `pm/pr-8020495`: history and timers
- `pm/pr-3ae2fc3`: spec-review pauses
- `pm/pr-ac10f03`: sign-off integration

## What the panel exposes today

- **List rows.** `pm_core/cli/session.py:948` `_LIST_ACTIONS = {start, review, qa, signoff, merge}`. These get rows for the PR named by the invoking window. Window patterns are at `session.py:935` (`#N`, `review-#N`, `qa-#N`, `signoff-#N`, `merge-#N`). QA is matched by prefix, so `qa-#N-sK` also counts as open.
- **Shortcut-only actions.** `edit`, plus `review-loop`, whose badge is folded onto the review row (`session.py:955`).
- **Fresh and loop variants.** `z`/`zz` prefixes (`session.py:921` `_MODIFIED_ACTION_CMDS`).
- **Row badges.** `[open]` comes from live tmux windows. `[idle] [wait] [working] [done V] [failed] [loop iN]` come from `runtime_state.derive_action_status` (`pm_core/runtime_state.py:316`), backed by hook events.
- **QA's sub-sessions** are not panel rows. They live in the `qa-#N` window and in per-scenario windows. The `qa-#N` status pane lists the scenarios, and Enter switches to a scenario window. **No direct path to a scenario's verifier exists**; the user moves to that window's bottom pane by hand.
- **Plan, meta, guide, watcher and ad-hoc Claude sessions** are reachable from the TUI or CLI, not the picker.

## Session kinds and how the glasses list them

| Session kind | PM window / pane role | Identity shown on glasses | Glasses location (mockup) | Picking it in PM today |
|---|---|---|---|---|
| Implementation | `#N` / `impl` (`impl-claude` with companion) | `#N Implementation` | PR sessions → Implementation | Existing window → switch; `z s` kills and relaunches |
| Review / review loop | `review-#N` / `review-claude` (+ `review-diff`); loop windows recreated per iteration | `#N Review loop`, state `loop iN` / `iN PASS` | PR sessions → Review | Switch. **Side effect: sets status `in_review`** (`pm_core/cli/pr.py:1417`). `zz d` always restarts the loop |
| QA planner | `qa-#N` / `qa-planner` (`pm_core/qa_loop.py:3512`) | `#N QA run R · QA planner` | PR sessions → QA run R → Planner | `t` focuses `qa-#N` |
| QA status dashboard | `qa-#N` / `qa-status` (`qa_loop.py:3513`) | not a session; its content is the QA run list itself | PR sessions → QA run R | — |
| QA interactive | `qa-#N-s0` / `qa-scenario-s0` (`qa_loop.py:1815`) | `#N QA run R · s0 Interactive` | QA run → s0 | via the status pane |
| QA scenario: refiner | `qa-#N-sK` / `qa-concretize-sK` (`qa_loop.py:2157`) | `#N QA run R · sK Refiner` + scenario title | QA run → sK → Refiner | via the status pane, then pane selection |
| QA scenario: execution worker | `qa-#N-sK` / `qa-scenario-sK` (`qa_loop.py:2158`). On relaunch the window is recreated **without** the refiner pane (`qa_loop.py:2505` `_relaunch_scenario_window`) | `#N QA run R · sK Execution`, `retry n` | QA run → sK → Execution | same |
| QA scenario: verifier | `qa-#N-sK` / `qa-verify-sK`, created lazily on the first PASS (`qa_loop.py:3393`) | `#N QA run R · sK Verifier`, `checking n/3`, `FLAGGED · retry n/3`, `VERIFIED` | QA run → sK → Verifier | **not directly reachable** |
| QA finalize | `qa-#N` / `qa-finalize` (`qa_loop.py:700`); split only after every scenario has a verdict (`qa_loop.py:4160`) | `#N QA run R · QA finalize`; `after all verdicts` until launched | QA run → Finalize | — (not user-startable) |
| Sign-off | `signoff-#N` / `signoff-claude` | `#N Sign-off`; verdict from `pr.signoff` | PR sessions → Sign-off | Switch, or launch. **Side effect: qa → sign_off.** No runtime badge writer exists |
| Merge / recovery | `merge-#N` / `merge-claude`. After pr-ac10f03 only the post-publish pull recovery remains | `#N Merge recovery` | PR sessions → Merge recovery (only when a window exists) | **Picking runs `pr merge --resolve-window`, i.e. attempts the merge** (`session.py:914`) |
| Edit | pane `pr-edit` (editor, not Claude) | — | not mirrored. PR metadata editing is a companion task (open question) | `e` |
| Spec review (V) | pane `spec-review` running `pm pr spec-approve` in an editor | replaced by the document reader + approve flow | Needs you / PR → Read spec | always fresh; oldest pending spec only |
| Plan add / breakdown / review / deps | window `<plan>` or `plan-deps`; roles `plan-add`, `plan-breakdown`, `plan-review`, `plan-deps`; `session_key plan:<step>:<plan>` (`pm_core/cli/plan.py:141,244,461,545`) | `Plan review` etc. under PLANS | Plans and project → PLANS | TUI only |
| Meta | window `meta` | `Meta` | Plans and project → PROJECT | TUI `m` |
| Guide | pane `guide` | `Guide` | Plans and project → PROJECT | TUI `H` |
| Watchers (discovery, bug-fix, improvement-fix) | windows `watcher`, `discovery`, `bug-fix-impl`, `improvement-fix-impl`; recreated per iteration | `Discovery watcher`, `iN running` / `iN READY` | Plans and project → WATCHERS | TUI / CLI |
| Ad-hoc Claude panes | roles `claude`, `discuss`, `watcher-review`, `qa-item`, `qa-author`, `qa-edit`, `qa-debug` | role + window, e.g. `Claude pane · #216` | PR sessions (when in a PR window) or Plans and project | TUI keys; per-window duplicate check only |

The mockup's fixture covers one of each kind above except Edit, Spec review (V) and `qa-status`, which are not conversations. Finalize appears in its pre-launch state, since the demo run still has scenarios without verdicts. See `mockup/src/fixtures.js`.

## Navigation shape demonstrated

```
Needs you ─┬─ document (spec/plan) ── actions ── Discuss → linked session
           ├─ QA scenario needing input → scenario sessions
           └─ manual merge → PR
Sessions ── PR ── Implementation | Review | QA run R ── Planner | s0 | s1…sK ── Refiner | Execution | Verifier
                                                      └ Finalize
           └─ Sign-off | Merge recovery | ad-hoc panes
Plans and project ── PLANS | PROJECT | WATCHERS
```

The session view's actions always offer:
- the scenario's other sessions
- all of the PR's sessions
- **Return to `<document> vN pP`** when the session was reached from a document

Back retraces the path (B10, B11 and B15 in the gallery).

## Rules the design adds on top of today's panel

1. **Opening is side-effect free.** Selecting a session that exists opens it ("Opened existing qa-verify-s2 · nothing launched"); it never runs `pr review`, `pr signoff` or `pr merge`.
2. **Starting is explicit.** A session that is not running offers "Start …" behind a confirmation that names PM's side effect: qa → sign_off, in_review, merge attempt, loop restart.
3. **One request per start.** Repeated selections while a start is pending report "Already starting" and join the pending request. Once PM reports the window, selection opens it.
4. **Identity survives recreation.** A session is identified by PR + role (+ QA run + scenario + helper, + iteration for loops), not by pane id. Review-loop and watcher windows are recreated per iteration, and worker relaunches change the pane layout.
5. **Ended sessions stay listed** with their transcript readable; starting a new one is a separate action.
6. **Attention propagates upward.** A scenario that needs input marks its QA run, its PR and Needs you (`?`).

## Gaps PM would have to close (input for pr-e5873d7)

These come from the audit. They are recorded as questions, not solutions, in [open-questions.md](open-questions.md#pm-actions-picker-sharing-pr-e5873d7).

- No single source enumerates all sessions:
  - QA helper pane and session ids live only in `qa_resume.json` (`qa_loop.py:799`).
  - Planner and finalize session ids are not persisted.
  - Sign-off has no runtime_state entry.
  - Meta, ad-hoc panes and the tmux impl path keep no resumable Claude id.
- "Verified" is not an explicit field in `qa_status.json`. It is a decorated verdict string, and scenario numbers are unique only within a run (`loop_id`).
- Duplicate-launch races:
  - `pr start` and `pr review` do find-then-create without a lock.
  - `start_qa` checks only the in-process loop.
  - Ad-hoc pane roles are checked per window.
- Picks with side effects (review, sign-off, merge, `zz t` toggle) have no "focus only" path the glasses could call.
