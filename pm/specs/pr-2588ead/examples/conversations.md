# Example setup and feedback conversations (pr-2588ead)

Supplements [`../impl.md`](../impl.md); prompts P2 and P3 (impl §1.3–1.4) are
authoritative. These are representative transcripts of what those prompts
should produce. The owner's lines are written as a plausible owner, the
assistant's lines follow the prompt rules, and command output is abridged with
`…`. Each transcript shows:

- how few questions the agent asks;
- how it separates explicit instructions from its own inferences, and scopes
  each preference to the right project;
- what it refuses (merge authority, dropping required content);
- how the change is shown and how it can be undone.

Projects and times are as in [`notes-and-state.md`](notes-and-state.md):
cosmic_ac and omerta-core are illustrative fixtures.

---

## 1. Setup: `pm brief setup` (Sun 1 Nov 2026, 14:39 CST)

P2 was rendered with no existing config or guidance
([`rendered-prompts.md`](rendered-prompts.md) §3).

> **Assistant:** I'll set up a short brief you can read in about a minute:
> what needs you, what changed and where each project stands. Here is what
> I'd start with:
>
> - **Projects:** project-manager (active today), cosmic_ac (active Friday)
>   and omerta-core. I can't read omerta-core's project.yaml right now;
>   including it means the brief tells you when it is unreadable instead of
>   leaving it out.
> - **When:** weekdays at 08:30, Central time.
> - **Where:** the project-manager dashboard. This machine only; email and
>   chat aren't available yet.
> - **Content:** what needs you first, then what changed, then where each
>   project stands, all short.
>
> Does that work? And is there anything you always want highlighted or never
> want to see?

> **Owner:** Yes, those three. Weekdays 8:30 is good. Lead with what needs me,
> I read it on my phone before standup. Keep it to about 25 lines.
> project-manager first when it's a tie. Don't list the old stale PRs, just
> count them. Tell me which plan a merge belongs to. cosmic merges rarely, so
> show each one.

```text
$ pm brief config projects add /home/matt/claude-work/project-manager/pm --name owner
created brief "owner" (schedule off) · added project-manager (828c8d0a)
$ pm brief config projects add /home/matt/claude-work/cosmic_ac/pm --name owner
added cosmic_ac (5e1c0a77)
$ pm brief config projects add /home/matt/claude-work/omerta/core/pm --name owner
added omerta-core (0e7a2b19) — warning: project.yaml not found; it will be reported as not refreshed
$ pm brief config cadence "weekdays 08:30" --name owner
cadence: weekdays 08:30 America/Chicago (schedule off; next brief only after `pm brief start`)
$ pm brief preview --name owner --prepare --guidance-file /tmp/brief-guidance-proposal.txt
preview run preview-20261101T204015Z-1c2d · input …/runs/preview-20261101T204015Z-1c2d/input.json
--- composing instructions (P1-P) follow ---
…
```

The agent composes the preview following P1-P, then runs `pm brief preview
--name owner --run preview-20261101T204015Z-1c2d --draft …/draft.json`.

> **Assistant:** Here's a preview built from your projects as they are right
> now (nothing is sent or saved yet):
>
> *(the rendered preview: the same shape as [`briefs.md`](briefs.md) §B1, with
> the facts as of Sunday afternoon)*
>
> I've filed your preferences like this:
>
> - **Whole brief:** lead with what needs you; about 25 lines; order projects
>   by what needs you, with project-manager first on ties.
> - **project-manager only:** count stale PRs instead of listing them; name
>   each merge's plan.
> - **cosmic_ac only:** show each merge on its own line.
>
> Does it read right? Say so and I'll save this and start the schedule.

> **Owner:** Looks good, start it.

```text
$ pm brief guidance show --name owner --json            # gets block shas (all empty)
$ pm brief guidance apply --name owner --scope whole --file /tmp/whole.txt --expect e3b0c442 \
    --quote "Lead with what needs me, I read it on my phone before standup. Keep it to about 25 lines. project-manager first when it's a tie." \
    --summary "initial whole-brief guidance from setup"
saved r-20261101T2041Z-1a2b · project-manager/pm/notes-brief.txt › Whole brief (not committed)
$ pm brief guidance apply --name owner --scope project --project 828c8d0a --file /tmp/pm.txt --expect e3b0c442 \
    --quote "Don't list the old stale PRs, just count them. Tell me which plan a merge belongs to." \
    --summary "initial project-manager guidance from setup"
saved r-20261101T2041Z-2c3d · project-manager/pm/notes-brief.txt › This project (not committed)
$ pm brief guidance apply --name owner --scope project --project 5e1c0a77 --file /tmp/cosmic.txt --expect e3b0c442 \
    --quote "cosmic merges rarely, so show each one." --summary "initial cosmic_ac guidance from setup"
saved r-20261101T2042Z-3e4f · cosmic_ac/pm/notes-brief.txt › This project (not committed)
$ pm brief start --name owner --quote "Looks good, start it."
brief "owner": schedule active · next brief Mon 2 Nov 2026 08:30 CST
$ pm brief guidance show --name owner
…(as in notes-and-state.md §1.5)…
$ pm brief status --name owner
brief "owner" · hub project-manager · schedule active · weekdays 08:30 America/Chicago
projects: project-manager ok · cosmic_ac ok · omerta-core not readable (project.yaml not found)
boundary: none yet (first brief is a baseline covering the previous 24h)
next brief: Mon 2 Nov 2026 08:30 CST · destination: local dashboard (project-manager)
```

> **Assistant:** Done. Your first brief arrives tomorrow at 08:30 on the
> project-manager dashboard (`pm pr dashboard`, or `pm brief show`). The
> guidance above is saved in each project's notes file; I haven't committed
> anything. To change anything later, run `pm brief feedback` and tell me in
> your own words.

What this transcript shows:

- One proposal message and one open question; no follow-up questions.
- The owner never saw a notes file or a config file.
- The agent stated where each preference was filed, and the owner accepted
  that ("Looks good").
- The schedule started only after "start it".
- Nothing was written for omerta-core, which the agent could not read.

---

## 2. Feedback with a correction, a refused request and a required item (Mon 2 Nov 2026, 09:10 CST)

`pm brief feedback "Too long, and I had to scroll for the things I need to do. Put everything that needs me in one list at the very top across all projects. Batch merges into one line per project. For cosmic_ac, skip notebook PRs unless they're stuck or waiting on me. And cosmic_ac doc-only PRs can just merge without me. Also stop showing the omerta thing, I know it's broken."`

> **Assistant:** Here's how I'd handle each part:
>
> 1. **One "Needs you" list at the top, across projects.** Clear, whole brief.
> 2. **"Too long".** The brief was 13 lines against your 25-line target. Shall
>    I make the target about 15?
> 3. **Batch merges into one line per project.** cosmic_ac's own guidance
>    says to show each merge, because it merges rarely. Keep that exception
>    for cosmic_ac, or batch there too?
> 4. **Skip cosmic_ac notebook PRs unless stuck or waiting on you.** I can
>    recognise them by titles that start with "Notebook:". Is that right?
> 5. **cosmic_ac doc-only PRs merging without you.** That's a change to who
>    may merge what, not to the brief, so I can't record it here; nothing the
>    brief does changes merge permissions. It belongs to the separate
>    merge-guidance setup, which isn't available yet. Until then cosmic_ac
>    keeps its current merge rules.
> 6. **Stop showing omerta-core.** I have to keep it: the brief always names
>    projects it couldn't refresh, so a project never silently drops out. I
>    can cut it to one short line.

> **Owner:** 15 is fine. Yes, the ones titled Notebook:. Keep listing cosmic
> merges one by one. Yes, one line for omerta is fine.

```text
$ pm brief guidance show --name owner --json
… "828c8d0a/Whole brief": {"sha": "7d41a9c0", …}, "5e1c0a77/This project": {"sha": "5b2e81d4", …} …
$ pm brief guidance apply --name owner --scope whole --file /tmp/whole.txt --expect 7d41a9c0 \
    --quote "Too long, and I had to scroll for the things I need to do. Put everything that needs me in one list at the very top across all projects. Batch merges into one line per project. … 15 is fine. … Yes, one line for omerta is fine." \
    --summary "top Needs-you list; ~15 lines; batch merges; one-line unrefreshed notices"
saved r-20261102T1514Z-5a6b · project-manager/pm/notes-brief.txt › Whole brief (not committed)
$ pm brief guidance apply --name owner --scope project --project 5e1c0a77 --file /tmp/cosmic.txt --expect 5b2e81d4 \
    --quote "For cosmic_ac, skip notebook PRs unless they're stuck or waiting on me. … Yes, the ones titled Notebook:. Keep listing cosmic merges one by one." \
    --summary "cosmic_ac: omit Notebook: PRs unless blocked/waiting; keep per-merge lines"
saved r-20261102T1515Z-7c8d · cosmic_ac/pm/notes-brief.txt › This project (not committed)
$ pm brief preview --name owner --prepare --rerender 20261102T143000Z-4f1a
…
```

> **Assistant:** Saved. The changes:
>
> *(the before/after diffs in [`notes-and-state.md`](notes-and-state.md) §2.1–2.2)*
>
> Here's this morning's brief again, same facts, with the new guidance:
>
> *(the preview in [`briefs.md`](briefs.md) §B1′)*
>
> Tomorrow's brief will list these changes at the bottom. To undo one, tell
> me, or run `pm brief guidance rollback <rev>`; the revisions are in
> `pm brief guidance history`.

What this transcript shows:

- **Clear instructions** (the Needs-you list, batching) were applied without
  extra questions.
- **Interpretations were confirmed first:** the 15-line target, "Notebook:"
  titles, the cosmic_ac exception, and the omerta-core short form.
- **The merge-authority request was declined, and nothing was recorded.**
  cosmic_ac's merge rules and every gate are unchanged.
- **The required item stays** (omerta-core), in the shortest form.
- **Only the affected blocks changed.** project-manager's `This project` block
  and every other section are untouched.

---

## 3. Undo a change: `pm brief feedback "Undo last week's change to the whole brief, the top list is noisy."` (Mon 9 Nov 2026, 09:30 CST)

```text
$ pm brief guidance history --name owner
project-manager › Whole brief
  r-20261102T1514Z-5a6b  2 Nov 09:14  owner-confirmed  top Needs-you list; ~15 lines; batch merges; one-line unrefreshed notices
  r-20261101T2041Z-1a2b  1 Nov 14:41  owner-confirmed  initial whole-brief guidance from setup
project-manager › This project
  r-20261101T2041Z-2c3d  1 Nov 14:41  owner-confirmed  initial project-manager guidance from setup
  (current file differs: direct edit not yet in history)
cosmic_ac › This project
  r-20261102T1515Z-7c8d  2 Nov 09:15  owner-confirmed  cosmic_ac: omit Notebook: PRs unless blocked/waiting; keep per-merge lines
  r-20261101T2042Z-3e4f  1 Nov 14:41  owner-confirmed  initial cosmic_ac guidance from setup
```

> **Assistant:** Last week's whole-brief change did four things: it added the
> top "Needs you" list, set the target to about 15 lines, batched merges, and
> shortened the notices for unrefreshed projects. Undoing it puts the whole
> brief back to your setup version: what needs you leads each project, about
> 25 lines. Undo all four, or only the top list? cosmic_ac's Notebook rule is
> a separate change and stays either way.

> **Owner:** All of it.

```text
$ pm brief guidance rollback r-20261102T1514Z-5a6b --name owner --quote "Undo last week's change to the whole brief, the top list is noisy. … All of it."
saved r-20261109T1531Z-f3a4 (rollback of r-20261102T1514Z-5a6b; restores r-20261101T2041Z-1a2b) · not committed
```

> **Assistant:** Done. The whole brief is back to the setup version, and the
> next brief will say so. One more thing: the line you added by hand on
> Tuesday, "Mention when a PR touching containers merges", stays as you wrote
> it. pm doesn't record which files a PR touches, so the brief can only catch
> merges whose titles mention containers. It says so when that applies.

What this transcript shows:

- Undo is explicit and confirmed in scope.
- History is appended to, never rewritten.
- The owner's direct edit is kept and its limits are stated.
- The resulting brief is [`briefs.md`](briefs.md) §B6.
