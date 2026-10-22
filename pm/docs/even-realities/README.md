# Even Realities plan/spec review: design checkpoint (pr-9e7847d)

Open **[index.html](index.html)** to review. It holds 54 glasses screenshots from Even's official simulator, grouped into four journeys, with captions and phone companion views. The same gallery is copied to this PR's PM captures directory (`even-realities/index.html`) so it can be opened from PM's report.

| Document | Contents |
|---|---|
| [proposal.md](proposal.md) | Required behavior: read → discuss in the right session → revise → approve the exact version → unattended PM; full session access including each QA scenario's refiner, worker and verifier; status, history, holds; busy, error and reconnect |
| [constraints.md](constraints.md) | G2 display, input, update, voice, lifecycle and companion constraints, each with a source and a verified/assumed label |
| [session-inventory.md](session-inventory.md) | Every session the PM actions panel and related windows expose, and how the glasses reach each one |
| [open-questions.md](open-questions.md) | Questions for pr-e5873d7 (PM picker sharing) and pr-9374887 (Pageborne sharing), plus hardware items for pr-1e0772a |
| [pageborne-snapshot.md](pageborne-snapshot.md) | Provenance of the Pageborne source reviewed (HEAD `4d769f60`, not committed) and the conventions adopted from it |
| [mockup/](mockup/README.md) | Runnable mockup, journey script, constraint checker and simulator capture |

Scope boundaries:
- No production PM or Pageborne code changed. Nothing under `pm_core/` was touched.
- The proposal defines behavior. The mockup's layout and gestures are one candidate.
- PM state, agent replies, revisions, connectivity and speech in the screenshots are **simulated**.
